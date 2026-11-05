"""Training visibility policy; never changes the provider recruitment status."""
import json
from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9))


def effective_start(row):
    """Naive DB timestamps are UTC; date-only starts expire at KST midnight."""
    value = row.get('starts_at')
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if isinstance(value, date):
        return datetime.combine(value, time.min, KST)
    extra = row.get('additional_sections') or {}
    if isinstance(extra, (str, bytes)):
        extra = json.loads(extra)
    raw = (extra.get('date_precision') or {}).get('starts_at', {}).get('raw')
    if raw:
        try:
            return datetime.combine(date.fromisoformat(raw), time.min, KST)
        except (TypeError, ValueError):
            pass
    return None


def start_visibility(row, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Training policy requires timezone-aware now')
    start = effective_start(row)
    if start is None:
        return False, 'start_unknown'
    return (True, 'before_start') if start > now else (False, 'training_started')


def _end(row):
    value=row.get('ends_at')
    if isinstance(value,datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if isinstance(value,date):return datetime.combine(value+timedelta(days=1),time.min,KST)
    extra=row.get('additional_sections') or {}
    if isinstance(extra,(str,bytes)):extra=json.loads(extra)
    raw=(extra.get('date_precision') or {}).get('ends_at',{}).get('raw')
    try:return datetime.combine(date.fromisoformat(raw)+timedelta(days=1),time.min,KST) if raw else None
    except (ValueError,TypeError):return None


def training_status(row,*,now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('Training policy requires timezone-aware now')
    start,end=effective_start(row),_end(row)
    if start is not None and end is not None and end<=start:schedule='unknown'
    elif end is not None and now>=end:schedule='ended'
    elif start is not None and now<start:schedule='upcoming'
    elif start is not None and end is not None:schedule='ongoing'
    else:schedule='unknown'
    schedule_label={'upcoming':'시작 예정','ongoing':'진행 중','ended':'종료','unknown':'일정 미확인'}[schedule]
    status=row.get('recruitment_status')
    extra=row.get('additional_sections') or {}
    if isinstance(extra,(str,bytes)):extra=json.loads(extra)
    deadline=row.get('application_deadline')
    raw=(extra.get('date_precision') or {}).get('application_deadline',{}).get('raw')
    elapsed=False
    if isinstance(deadline,datetime):elapsed=(deadline.replace(tzinfo=timezone.utc) if deadline.tzinfo is None else deadline)<=now
    elif raw:
        try:elapsed=date.fromisoformat(raw)<now.astimezone(KST).date()
        except (ValueError,TypeError):pass
    recruitment='closed' if status=='closed' else 'deadline_elapsed' if elapsed else 'open_recorded' if status=='active' else 'unknown'
    recruitment_label={'closed':'마감으로 기록','deadline_elapsed':'신청 마감일 경과','open_recorded':'모집 중으로 기록','unknown':'모집 여부 미확인'}[recruitment]
    return {'schedule_status':schedule,'schedule_label':schedule_label,
            'recruitment_display_status':recruitment,'recruitment_label':recruitment_label,
            'status_evaluated_at':now.isoformat()}


def refresh_card_status(course,*,now=None):
    """Recompute dates for saved public cards; never infer fresh provider verification."""
    now=now or datetime.now(timezone.utc)
    row=dict(course,additional_sections={'date_precision':course.get('dates') or {}})
    # Public timestamp fields are ISO strings; date-only provenance remains in dates.
    for field in ('starts_at','ends_at','application_deadline'):
        value=row.get(field)
        if isinstance(value,str):
            try:row[field]=datetime.fromisoformat(value.replace('Z','+00:00'))
            except ValueError:row[field]=None
    status=training_status(row,now=now)
    result=dict(course,**status)
    eligible=course.get('recommendation_eligible') is True and status['schedule_status']=='upcoming' and status['recruitment_display_status']=='open_recorded'
    result['recommendation_eligible']=eligible
    result['usage']='application_candidate' if eligible else 'historical_learning_reference' if status['schedule_status']=='ended' else 'learning_reference'
    result['warning']=None if eligible else status['schedule_label']+' · '+status['recruitment_label']+' 자료입니다. 신청 기간·현재 모집 여부·지원 자격은 원문 또는 교육기관에서 확인해 주세요.'
    return result
