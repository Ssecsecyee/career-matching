import React,{useRef} from 'react';
export function clampChatWidth(value,total){return Math.max(260,Math.min(value,680,Math.max(260,total-468)));}
export function SplitHandle({width,onResize}){
 const drag=useRef(null);
 const total=el=>el.parentElement.getBoundingClientRect().width||window.innerWidth;
 return <div className="workspace-resizer" role="separator" aria-label="채팅과 목록 너비 조절" aria-orientation="vertical" tabIndex={0} aria-valuemin={260} aria-valuemax={680} aria-valuenow={Math.round(width)}
 onPointerDown={e=>{if(e.button!==0)return;drag.current={x:e.clientX,width};e.currentTarget.setPointerCapture?.(e.pointerId);e.preventDefault();}}
 onPointerMove={e=>{if(drag.current)onResize(clampChatWidth(drag.current.width+e.clientX-drag.current.x,total(e.currentTarget)));}}
 onPointerUp={e=>{drag.current=null;if(e.currentTarget.hasPointerCapture?.(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);}}
 onPointerCancel={()=>{drag.current=null;}}
 onKeyDown={e=>{if(!['ArrowLeft','ArrowRight','Home'].includes(e.key))return;e.preventDefault();onResize(clampChatWidth(e.key==='Home'?340:width+(e.key==='ArrowRight'?20:-20),total(e.currentTarget)));}}><span/></div>;
}
