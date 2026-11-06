export function filterItems(items,{keyword='',region='',extra='',jobs=true}={}){
 const q=keyword.trim().toLocaleLowerCase(),x=extra.trim().toLocaleLowerCase();
 return items.filter(item=>{
 const area=(item.addresses||[])[0]?.trim().split(/\s+/)[0]||'';
 const hay=[item.title,item.company_name,item.provider_name,...(item.tech_stacks||[])].filter(Boolean).join(' ').toLocaleLowerCase();
 const mode=['online','offline'].includes(item.delivery_mode)?item.delivery_mode:'unknown';
 return (!region||region===area)&&(!q||hay.includes(q))&&(!x||(jobs?(item.tech_stacks||[]).some(t=>t.toLocaleLowerCase().includes(x)):mode===x));
 });
}
export function pageItems(items,page,size=20){return items.slice((page-1)*size,page*size);}
