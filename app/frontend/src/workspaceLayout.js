export function defaultCardWidth(total){return Math.max(280,(total-340-8-40-28)/3);}
export function clampChatWidth(value,total){
 const required=2*defaultCardWidth(total)+14+40+8;
 return Math.max(260,Math.min(value,680,Math.max(260,total-required)));
}
export function catalogColumns(total,chatWidth){
 if(total<=1000)return 1;
 return Math.max(2,Math.floor((total-chatWidth-8-40+14)/(defaultCardWidth(total)+14)+0.00001));
}
