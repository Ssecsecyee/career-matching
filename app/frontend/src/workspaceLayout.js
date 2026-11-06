export function clampChatWidth(value,total){return Math.max(260,Math.min(value,680,Math.max(260,total-648)));}
export function catalogColumns(total,chatWidth){
 if(total<=1000)return 1;
 const available=total-chatWidth-8;
 return Math.max(2,Math.floor((available-40+14)/454));
}
