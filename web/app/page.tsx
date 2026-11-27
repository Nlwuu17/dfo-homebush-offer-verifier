'use client';
import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {useEffect,useState,FormEvent} from 'react';
import {api,todaySydney} from './tracker';
type Index={records:{id:string;brand:string;created_at:string}[];llm_available:boolean;availability_reason:string|null;model:string};
export default function Tracker(){
 const router=useRouter();const [info,load]=useState<Index|null>(null),[error,fail]=useState(''),[busy,waiting]=useState(false),[day,date]=useState('');
 useEffect(()=>{date(todaySydney());api<Index>('/api/records').then(load).catch(e=>fail(e.message))},[]);
 async function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();const f=new FormData(e.currentTarget);if(!String(f.get('text')).trim()&&!String(f.get('url')).trim()){fail('请至少填写优惠链接或具体文案。');return}waiting(true);fail('');
 try{const r=await api<{id:string}>('/api/records',{brand:f.get('brand'),text:f.get('text'),url:f.get('url')||null,day,mode:f.get('mode')});router.push('/records/'+r.id)}catch(err){fail((err as Error).message);waiting(false)}}
 return <main><nav>DFO <span>HOMEBUSH</span><small><Link href="/compare">策略对照 ↗</Link></small></nav><h1>优惠核对与追踪</h1>
 <div className="workspace"><form onSubmit={submit} className="sheet"><h2>核对一条优惠</h2>
 <label>品牌<input name="brand" required maxLength={100} placeholder="Tommy Hilfiger"/></label>
 <label>官方优惠链接<input name="url" type="url" placeholder="https://…"/></label>
 <label>优惠文案<textarea name="text" maxLength={3000} placeholder="例如：全店按原价减 50%"/></label>
 <p className="hint">链接和文案可任选一项。同时填写时，两者须指向同一优惠。</p>
 <div className="pair"><label>核对日期（悉尼）<input required type="date" value={day} onChange={e=>date(e.target.value)}/></label>
 <label>查询方式<select name="mode"><option value="offline">离线规则</option><option value="llm" disabled={!info?.llm_available}>LLM 选择证据</option></select></label></div>
 {info&&!info.llm_available&&<small>LLM 不可用 · {info.availability_reason}</small>}
 {error&&<p role="alert">{error}</p>}<button disabled={busy}>{busy?'正在核对…':'核对并保存 →'}</button></form>
 <aside className="sheet"><h2>最近的核对记录</h2>{!info?'正在读取…':info.records.length?info.records.map(r=><p key={r.id}><Link href={'/records/'+r.id}>{r.brand} ↗</Link><br/><small>{new Date(r.created_at).toLocaleString('zh-CN',{timeZone:'Australia/Sydney'})}</small></p>):'还没有保存的记录。'}</aside></div></main>
}
