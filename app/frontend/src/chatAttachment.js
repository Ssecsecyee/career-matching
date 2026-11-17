export const TXT_MAX_BYTES=20000;
export async function readTxtAttachment(file){
 if(!file || !/\.txt$/i.test(file.name) || file.size>TXT_MAX_BYTES)throw new Error('20KB 이하 TXT 파일을 선택해 주세요.');
 let text;
 try{text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());}
 catch{throw new Error('UTF-8 TXT 파일로 저장한 뒤 다시 첨부해 주세요.');}
 if(!text.trim() || text.includes('\0'))throw new Error('내용이 있는 텍스트 파일을 선택해 주세요.');
 if(new TextEncoder().encode(text).length>TXT_MAX_BYTES)throw new Error('TXT 내용을 20KB 이하로 줄여주세요.');
 return {name:file.name,text};
}
export function attachmentSearchText(attachment,draft=''){
 const text=attachment.text+(draft.trim()?'\n\n추가 검색 조건:\n'+draft.trim():'');
 if(new TextEncoder().encode(text).length>TXT_MAX_BYTES)throw new Error('첨부 내용과 메시지를 합쳐 20KB 이하로 줄여주세요.');
 return text;
}
