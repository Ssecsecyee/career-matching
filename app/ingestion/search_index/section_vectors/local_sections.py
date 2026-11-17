"""Local CPU section embeddings. No cloud inference, truncation, or user-text cache."""
import hashlib,json,math
from pathlib import Path

MODEL_ID='onnx-community/gte-multilingual-base'
REVISION='2edbf5e672aab465f9ed4c154a8b61791c082c69'
DIMENSIONS=768
SECTIONS=('qualifications','preferred_requirements')
def digest(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()
def model_contract():
 return {'model':MODEL_ID,'revision':REVISION,'file':'model_int8.onnx','dimensions':DIMENSIONS,'pooling':'cls_l2','section_policy':'whole-section-v1'}
def fingerprint():return digest(json.dumps(model_contract(),sort_keys=True))
def section_records(row,es_id):
 if not all(isinstance(row.get(k),str) and row[k] for k in ('source','source_id','source_version')):
  raise ValueError('source_identity_and_version_required')
 out=[]
 for section in SECTIONS:
  text=row.get(section) or ''
  if not isinstance(text,str):raise ValueError('section_must_be_text')
  if not text.strip():continue
  out.append({'es_id':es_id,'source':row['source'],'source_id':row['source_id'],'source_version':row['source_version'],
              'section':section,'text':text,'section_hash':digest(text),
              'cache_key':digest(fingerprint()+':'+section+':'+text)})
 return out
def valid_vector(v):
 if len(v)!=DIMENSIONS or any(not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(x) for x in v):raise ValueError('invalid_vector')
 if abs(sum(x*x for x in v)-1)>0.01:raise ValueError('vector_not_normalized')
 return v
class LocalEmbedder:
 def __init__(self,model_dir,max_tokens=2048):
  import numpy as np
  import onnxruntime as ort
  from tokenizers import Tokenizer
  if not 8<=max_tokens<=8192:raise ValueError('invalid_token_limit')
  self.np=np;self.max_tokens=max_tokens;root=Path(model_dir)
  manifest=json.loads((root/'manifest.json').read_text())
  if manifest['contract']!=model_contract():raise ValueError('model_contract_mismatch')
  for name,expected in manifest['sha256'].items():
   h=hashlib.sha256()
   with (root/name).open('rb') as f:
    for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
   if h.hexdigest()!=expected:raise ValueError('model_checksum_mismatch')
  self.tokenizer=Tokenizer.from_file(str(root/'tokenizer.json'));self.tokenizer.no_truncation();self.tokenizer.no_padding()
  opts=ort.SessionOptions();opts.intra_op_num_threads=1;opts.inter_op_num_threads=1
  opts.enable_cpu_mem_arena=False;opts.enable_mem_pattern=False
  self.session=ort.InferenceSession(str(root/'model_int8.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
 def token_count(self,text):
  if not isinstance(text,str) or not text.strip():raise ValueError('nonempty_text_required')
  return len(self.tokenizer.encode(text).ids)
 def encode(self,text):
  # Preserve the whole input. Reject rather than silently truncate long sections/resumes.
  e=self.tokenizer.encode(text);n=len(e.ids)
  if not text.strip():raise ValueError('nonempty_text_required')
  if n>self.max_tokens:raise ValueError('input_exceeds_token_limit:'+str(n))
  np=self.np;values={'input_ids':e.ids,'attention_mask':e.attention_mask,'token_type_ids':e.type_ids}
  feed={x.name:np.array([values[x.name]],dtype=np.int64) for x in self.session.get_inputs()}
  outputs=self.session.run(None,feed);hidden=outputs[0]
  if hidden.ndim!=3 or hidden.shape[2]!=DIMENSIONS:raise ValueError('unexpected_model_output')
  v=hidden[0,0,:].astype(np.float32);norm=np.linalg.norm(v)
  if not np.isfinite(norm) or norm<=0:raise ValueError('zero_or_invalid_embedding')
  v=(v/norm).tolist()
  return valid_vector(v),n
