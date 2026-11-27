'use client';
import Link from 'next/link';
import {useParams} from 'next/navigation';
import {useEffect,useState,FormEvent} from 'react';
import {api,RecordData} from '../../tracker';
export default function RecordPage(){
 const {id}=useParams<{id:string}>();const path='/api/records/'+id;
 const [data,set]=useState<RecordData|null>(null),[index,pick]=useState(0),[url,source]=useState(''),[error,fail]=useState(''),[busy,wait]=useState(false);
 useEffect(()=>{let live=true;set(null);api<RecordData>(path).then(d=>{if(live){set(d);pick(d.versions.length-1)}}).catch(e=>live&&fail(e.message));return()=>{live=false}},[path]);
 async function check(e:FormEvent){e.preventDefault();if(!data)return;wait(true);fail('');try{const d=await api<RecordData>(path+'/recheck',{expected_version:data.versions.length,evidence_url:url||null});set(d);pick(d.versions.length-1);source('')}catch(e){fail((e as Error).message)}finally{wait(false)}}
 const v=data?.versions[index],r=v?.result,prev=data?.versions[index-1]?.result;
 const prior=new Map(prev?.snapshots.map(s=>[s.id,JSON.stringify(s)]));
 return <main><nav>DFO <span>HOMEBUSH</span><small><Link href="/">返回核对首页</Link></small></nav>{error&&<p role="alert">{error}</p>}{!data||!v||!r?<p>{error?'无法打开记录。':'正在读取已保存记录…'}</p>:<>
 <h1>{data.submission.brand}</h1><p>{data.submission.text||data.submission.url}</p><small>核对日期 {data.submission.day} · DFO Homebush</small>
 <div className="workspace"><article><label>历史版本 <select value={index} onChange={e=>pick(Number(e.target.value))}>{data.versions.map((s,i)=><option key={s.version} value={i}>第 {s.version} 版</option>)}</select></label>
 <h2 className="verdict">{r.label}</h2><p>{r.reason}</p><small>{r.stop} · {r.trace.length} 次查询 · {r.model? r.model+' / '+r.calls.length+' 次调用':'离线规则'}</small>
 {prev&&<section><h3>与上一版比较</h3><p>{prev.label} → {r.label}</p>
 <p>新增或更新的证据：{r.snapshots.filter(s=>prior.get(s.id)!==JSON.stringify(s)).map(s=>s.id).join('、')||'无'}<br/>本版未读取：{prev.snapshots.filter(s=>!r.snapshots.some(n=>n.id===s.id)).map(s=>s.id).join('、')||'无'}</p></section>}
 <h3>证据与查询轨迹</h3>{r.snapshots.length===0&&<p>没有匹配到可引用的资料。</p>}{r.snapshots.map((s,i)=><section key={s.id} className="citation"><small>{s.id} · {r.citations.includes(s.id)?'结论引用':'已读资料'}{s.test_only?' · 测试资料':''}</small><h4><a href={s.url} target="_blank" rel="noreferrer">{s.title} ↗</a></h4><p>{s.scope_text} {s.start&&s.start+' 至 '+s.end}</p>{s.passages.map(p=><div key={p.locator}><small>{p.locator}</small><p>{p.summary_zh}</p>{p.quote&&<blockquote>{p.quote}</blockquote>}</div>)}<small>资料核对日期 {s.checked_date} · 悉尼<br/>{i+1}. {r.trace[i]?.selection_reason}</small></section>)}</article>
 <form onSubmit={check} className="sheet"><h2>重新核对</h2><p>重新读取已登记的官方资料，保存为第 {data.versions.length+1} 版。</p>
 <label>补充证据链接（可选）<input type="url" value={url} onChange={e=>source(e.target.value)} placeholder="已登记的官方资料 URL"/></label>
 {data.versions[data.versions.length-1].result.supplements.map(s=><button type="button" className="alt" key={s.url} onClick={()=>source(s.url)}>选用：{s.title}</button>)}
 <button disabled={busy}>{busy?'正在核对…':'保存新的核对版本'}</button></form></div></>}</main>
}
