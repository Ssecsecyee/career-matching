export const GUIDE_KEY='educare:workspace-guide:v1';
export function guideSeen(storage){try{return storage.getItem(GUIDE_KEY)==='done';}catch{return false;}}
export function rememberGuide(storage){try{storage.setItem(GUIDE_KEY,'done');}catch{/* The guide still closes when storage is unavailable. */}}
export function placeGuide(rects,width,height,viewport){
 const gap=14,left=viewport.left+12,top=viewport.top+12,right=viewport.left+viewport.width-width-12,bottom=viewport.top+viewport.height-height-12;
 const candidates=rects.flatMap(r=>[{x:r.left,y:r.bottom+gap},{x:r.left,y:r.top-height-gap},{x:r.right+gap,y:r.top},{x:r.left-width-gap,y:r.top}]);
 candidates.push({x:left,y:bottom},{x:right,y:top},{x:left,y:top},{x:(left+right)/2,y:(top+bottom)/2});
 return candidates.map((p,i)=>{const x=Math.max(left,Math.min(p.x,right)),y=Math.max(top,Math.min(p.y,bottom));const overlap=rects.reduce((n,r)=>n+Math.max(0,Math.min(x+width,r.right)-Math.max(x,r.left))*Math.max(0,Math.min(y+height,r.bottom)-Math.max(y,r.top)),0);return {x,y,score:overlap+i*.01};}).sort((a,b)=>a.score-b.score)[0];
}
