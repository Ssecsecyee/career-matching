import test from 'node:test';
import assert from 'node:assert/strict';
import {readTxtAttachment,attachmentSearchText} from './chatAttachment.js';
const file=(name,text)=>({name,size:new TextEncoder().encode(text).length,arrayBuffer:async()=>new TextEncoder().encode(text).buffer});
test('TXT attachment preserves complete Unicode conditions',async()=>{
 const result=await readTxtAttachment(file('experience.TXT','Python 또는 Java\n부산 경남'));
 assert.equal(result.text,'Python 또는 Java\n부산 경남');
});
test('only TXT, valid UTF-8, nonempty files within byte budget',async()=>{
 for(const input of [file('cv.pdf','Python'),file('cv.txt',' '),file('cv.txt','a\0b'),file('cv.txt','가'.repeat(7000)),{name:'cv.txt',size:1,arrayBuffer:async()=>new Uint8Array([255]).buffer}])await assert.rejects(()=>readTxtAttachment(input));
});
test('filename stays local and message is combined once',()=>{
 assert.equal(attachmentSearchText({name:'private-name.txt',text:'Python'},'Docker'),'Python\n\n추가 검색 조건:\nDocker');
 assert.equal(attachmentSearchText({text:'Python'},''),'Python');
 assert.throws(()=>attachmentSearchText({text:'a'.repeat(20000)},'x'));
});
