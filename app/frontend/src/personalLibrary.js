const KEY='career.personal.v1';
export const emptyLibrary=()=>({recent:[],saved:[]});
export const itemKey=item=>String(item.source||'jumpit')+':'+String(item.source_id);
export function readLibrary(storage){try{const value=JSON.parse(storage.getItem(KEY));if(!value||!Array.isArray(value.recent)||!Array.isArray(value.saved))return emptyLibrary();return {recent:value.recent.slice(0,100),saved:value.saved.slice(0,200)};}catch{return emptyLibrary();}}
export function writeLibrary(storage,value){storage.setItem(KEY,JSON.stringify(value));}
export function addRecent(library,item,target,now=new Date().toISOString()){const entry={...item,target,viewedAt:now};return {...library,recent:[entry,...library.recent.filter(x=>itemKey(x)!==itemKey(item))].slice(0,100)};}
export function toggleSaved(library,item,target){const exists=library.saved.some(x=>itemKey(x)===itemKey(item));return {...library,saved:exists?library.saved.filter(x=>itemKey(x)!==itemKey(item)):[{...item,target},...library.saved].slice(0,200)};}
