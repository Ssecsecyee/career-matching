import React,{useRef,useState} from 'react';
import {readTxtAttachment} from './chatAttachment.js';

export function ChatAttachment({value,onChange,disabled,onLoading}){
 const input=useRef(null),generation=useRef(0);
 const [loading,setLoading]=useState(false),[error,setError]=useState('');
 async function select(file){
  const id=++generation.current;setError('');onChange(null);
  if(!file)return;
  setLoading(true);onLoading(true);
  try{const next=await readTxtAttachment(file);if(id===generation.current)onChange(next);}
  catch(e){if(id===generation.current)setError(e.message);}
  finally{if(id===generation.current){setLoading(false);onLoading(false);}}
 }
 return <div className="chat-attachment">
  <input ref={input} type="file" accept=".txt,text/plain" hidden disabled={disabled || loading} onChange={e=>{const file=e.target.files?.[0];e.target.value='';select(file);}}/>
  <button className="attach-button" type="button" aria-label="TXT 파일 첨부" title="TXT 파일 첨부 (UTF-8, 20KB 이하)" disabled={disabled || loading} onClick={()=>input.current?.click()}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg></button>
  {loading?<small role="status">파일 읽는 중…</small>:value?<span className="attachment-chip"><span title={value.name}>{value.name}</span><button type="button" aria-label="첨부 파일 제거" disabled={disabled} onClick={()=>{++generation.current;onChange(null);setError('');}}>×</button></span>:<small>TXT 첨부로 유사 공고 검색</small>}
  {error&&<small className="attachment-error" role="alert">{error}</small>}
 </div>;
}
