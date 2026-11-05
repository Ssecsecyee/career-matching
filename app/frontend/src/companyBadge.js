const palette=['#6954ce','#217b78','#2874c4','#ad4942','#ab4d8c','#596e3c','#996022','#426789'];
export function companyColor(name='') {
 let hash=0;for(const char of name.trim())hash=(Math.imul(hash,31)+char.codePointAt(0))>>>0;
 return palette[hash%palette.length];
}
