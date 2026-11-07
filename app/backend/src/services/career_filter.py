"Missing career evidence never proves entry-level eligibility."
import json
import re

def entry_eligible(row):
 source=row.get('career_source') or {}
 if isinstance(source,str):
  try:source=json.loads(source)
  except (ValueError,TypeError):source={}
 if not isinstance(source,dict):source={}
 title=str(row.get('title') or '')
 qualifications=str(row.get('qualifications') or '')
 # Only explicit eligibility wording is accepted; mentions such as mentoring new hires do not count.
 if re.search(r'경력\s*무관|신입\s*(?:가능|지원\s*가능|지원자?\s*가능|환영|채용)|신입\s*[/·,및또는]+\s*경력|(?:^|[\s(\[])신입(?:$|[\s)\]/·,])',title):return True
 if re.search(r'경력\s*무관|신입(?:도|자도)?\s*(?:지원\s*)?가능|신입\s*환영',qualifications):return True
 return source.get('newcomer') is True

def filter_career(rows,plan):
 if plan.schema_version==2 and plan.career.levels==('entry',):
  return [r for r in rows if entry_eligible(r)]
 return rows
