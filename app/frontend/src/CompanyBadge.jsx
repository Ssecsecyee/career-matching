import React from 'react';
import {companyColor} from './companyBadge.js';
export function CompanyBadge({name}) {
 const text=(name || '기관 미확인').trim();
 return <span className="company-badge" style={{backgroundColor:companyColor(text)}} aria-hidden="true" title={text}>{text.length>10?text.slice(0,9)+'…':text}</span>;
}
