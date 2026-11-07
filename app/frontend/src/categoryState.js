export function categoryValues(plan){
 return {keyword:plan?.text_query || plan?.keyword || '',roles:plan?.roles || [],regions:plan?.regions || (plan?.region?[plan.region]:[]),skills:plan?.required_skills || plan?.skills || [],entry:plan?.career?.levels?.length===1 && plan.career.levels[0]==='entry'};
}
export function categoryRequest(value,base){
 const previous=base?.schema_version===2?base:{};
 return {action:'search',values:{page_size:20,preserve_current:false,search_plan:{
 schema_version:2,target:'jobs',limit:20,text_query:value.keyword.trim(),regions:value.regions,roles:value.roles,
 required_skills:value.skills,owned_skills:previous.owned_skills || [],preferred_skills:previous.preferred_skills || [],
 career:value.entry?{levels:['entry']}:(previous.career?.levels?.includes('entry')?{levels:[]}:previous.career || {levels:[]})}}};
}

export function categoryTextRequest(value,base){
 const request=categoryRequest(value,base);
 return {action:'search',values:{page_size:20,message:value.keyword.trim(),catalog_plan:{...request.values.search_plan,text_query:''}}};
}
