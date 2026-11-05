import assert from 'node:assert/strict';
import test from 'node:test';
import {companyColor} from './companyBadge.js';
test('name badges keep a stable color and use multiple backgrounds',()=>{
 assert.equal(companyColor('기업 A'),companyColor('기업 A'));
 assert.equal(companyColor(' 기업 A '),companyColor('기업 A'));
 assert.ok(new Set(['기업 A','기업 B','기업 C'].map(companyColor)).size>1);
});
test('badge backgrounds keep white company names readable',()=>{
 for(const name of ['A','B','C','D','E','F','G','H']){
  const hex=companyColor(name).slice(1),rgb=[0,2,4].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  const luminance=.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];assert.ok(1.05/(luminance+.05)>=4.5);
 }
});
