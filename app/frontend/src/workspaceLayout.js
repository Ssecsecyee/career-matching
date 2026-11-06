export function clampChatWidth(value,total){return Math.max(260,Math.min(value,680,Math.max(260,total-648)));}
export function catalogColumns(total,chatWidth){
 if(total<=1000)return 1;
 const available=total-chatWidth-8;
 return available<840?2:available<1680?3:4+Math.floor((available-1680)/560);
}
