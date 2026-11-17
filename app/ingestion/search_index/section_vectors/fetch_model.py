"""Download a pinned ONNX artifact, never execute remote model Python."""
import argparse,hashlib,json,os,urllib.request
from pathlib import Path
from local_sections import MODEL_ID,REVISION,model_contract
def fetch(dest):
 root=Path(dest);root.mkdir(parents=True,exist_ok=True);hashes={}
 for remote,name in [('onnx/model_int8.onnx','model_int8.onnx'),('tokenizer.json','tokenizer.json'),('config.json','config.json')]:
  url='https://huggingface.co/'+MODEL_ID+'/resolve/'+REVISION+'/'+remote
  target=root/name;partial=target.with_suffix(target.suffix+'.partial')
  if not target.exists():
   with urllib.request.urlopen(url,timeout=120) as r,partial.open('wb') as f:
    for chunk in iter(lambda:r.read(1024*1024),b''):f.write(chunk)
   os.replace(partial,target)
  h=hashlib.sha256()
  with target.open('rb') as f:
   for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
  hashes[name]=h.hexdigest();print(name+' ready',flush=True)
 (root/'manifest.json').write_text(json.dumps({'contract':model_contract(),'sha256':hashes},indent=2),encoding='utf-8')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);fetch(p.parse_args().output)
