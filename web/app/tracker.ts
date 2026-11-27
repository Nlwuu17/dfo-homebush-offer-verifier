export async function api<T>(path:string,body?:unknown):Promise<T>{
  const response=await fetch(path,{cache:'no-store',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
  if(!response.ok){const err=await response.json().catch(()=>({}));throw new Error(typeof err.detail==='string'?err.detail:'请求失败，请核对输入或检查本地服务。')}
  return response.json();
}
export type RecordData={id:string;submission:{brand:string;text:string;url:string|null;day:string;mode:string};versions:Revision[]};
type Snap={id:string;title:string;url:string;checked_date:string;start?:string;end?:string;scope_text?:string;test_only?:boolean;passages:{locator:string;summary_zh:string;quote?:string}[]};
type Revision={version:number;saved_at:string;attached:string[];result:{label:string;reason:string;status?:string;stop:string;citations:string[];trace:{source_id:string;selection_reason:string}[];snapshots:Snap[];supplements:{title:string;url:string}[];model:string|null;calls:unknown[]}};
export function todaySydney(){
 const fields=new Intl.DateTimeFormat('en-CA',{timeZone:'Australia/Sydney',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
 return ['year','month','day'].map(k=>fields.find(p=>p.type===k)?.value).join('-');
}
