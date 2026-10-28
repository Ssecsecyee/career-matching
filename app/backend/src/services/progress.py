"""Best-effort, throttled draft snapshots; failure never repeats a model call."""
from time import monotonic

class ProgressPublisher:
    def __init__(self,store,job_id,*,clock=monotonic):
        self.store,self.job_id,self.clock=store,job_id,clock
        self.last_time=-float('inf');self.last='';self.version=0;self.disabled=False

    def __call__(self,text):
        if self.disabled or not isinstance(text,str) or not text or len(text)>5000:return
        if not text.startswith(self.last) or text==self.last:return
        now=self.clock()
        if now-self.last_time<0.8:return
        try:
            self.version+=1
            self.store.progress(self.job_id,text,self.version)
            self.last=text;self.last_time=now
        except Exception:
            # The final response still follows the authoritative completion path.
            self.disabled=True
