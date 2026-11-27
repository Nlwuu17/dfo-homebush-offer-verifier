'use client';
import {useEffect,useRef,useState} from 'react';
type Arm='A'|'B'|'C';
type Case={case_id:string;brand:string;offer:string};
type Catalogue={cases:Case[];llm_available:boolean;availability_reason:string|null;model:string};
type Passage={locator:string;summary_zh:string;quote?:string};
type Step={step:number;source_id:string;selection_reason:string;label:string;reason:string;evidence:{title:string;url:string;checked_date:string;passages:Passage[]}};
type Call={number:number;status:string;latency_ms:number;model:string;tools:{name:string;arguments:string}[];input_tokens:number|null;output_tokens:number|null;cost_usd:number|null};
type Result={label:string|null;status:string;reason:string;stop_reason:string;query_count:number;citations:string[];steps:Step[];model_calls:number;latency_ms:number;cost_usd:number|null;model:string|null;calls:Call[]};
type Slot={result?:Result;error?:string;loading?:boolean};
const names={A:'固定查询',B:'规则策略',C:'LLM Agent'};
const arms:Arm[]=['A','B','C'];
async function request<T>(path:string,options?:RequestInit):Promise<T>{
  const res=await fetch(path,{cache:'no-store',...options});
  if(!res.ok) throw Error('API 请求失败（HTTP '+res.status+'）');
  return res.json();
}
function Card({arm,state,unavailable}:{arm:Arm;state:Slot;unavailable:string|null}){
  const r=state.result;
  return <article aria-label={names[arm]}>
    <header><span className="letter">{arm}</span><h3>{names[arm]}</h3></header>
    {unavailable?<p role="status"><b>LLM 不可用</b><br/>{unavailable}</p>:state.loading?<p role="status">正在核对…</p>:state.error?<p role="alert">{state.error}</p>:!r?<p>选中此策略并运行以查看结果。</p>:<>
    <div className={'verdict '+(r.label==='适用'?'yes':r.label==='不适用'?'no':'unknown')}>{r.status==='error'?'运行中止 · ':''}{r.label||'未运行'}</div>
    <p>{r.reason}</p><dl><dt>文档查询</dt><dd>{r.query_count} / 3</dd><dt>结论引用</dt><dd>{r.citations.join(' · ')||'无'}</dd><dt>停止原因</dt><dd>{r.stop_reason}</dd></dl>
    {arm==='C'&&<><dl><dt>模型</dt><dd>{r.model}</dd><dt>调用 / 耗时</dt><dd>{r.model_calls} 次 / {r.latency_ms} ms</dd><dt>费用 USD</dt><dd>{r.cost_usd===null?'未取得':r.cost_usd}</dd></dl>
    {r.calls.map(c=><details key={c.number}><summary>模型调用 {c.number} · {c.status}</summary><p>{c.model} · {c.latency_ms} ms<br/>Token 入 / 出　{c.input_tokens??'未取得'} / {c.output_tokens??'未取得'}</p>{c.tools.map((t,i)=><code key={i}>{t.name} {t.arguments}</code>)}</details>)}</>}
    <h4>查询轨迹</h4>{r.steps.map(s=><details key={s.step}><summary><span>{String(s.step).padStart(2,'0')}</span> {s.source_id} · {s.label}</summary><p>{s.selection_reason}</p><strong>{s.evidence.title}</strong>{s.evidence.passages.map(p=><section key={p.locator}><small>{p.locator}</small><p>{p.summary_zh}</p>{p.quote&&<blockquote>{p.quote}</blockquote>}</section>)}<a href={s.evidence.url} target="_blank" rel="noreferrer">官方原页 ↗</a><small>　核对于 {s.evidence.checked_date}</small></details>)}</>}
  </article>
}
function Comparison({item,cat}:{item:Case;cat:Catalogue}){
  const [selected,select]=useState<Arm[]>(['A','B']);
  const [slots,setSlots]=useState<Partial<Record<Arm,Slot>>>({});
  const controller=useRef<AbortController|null>(null);
  useEffect(()=>()=>controller.current?.abort(),[]);
  const run=async()=>{
    controller.current?.abort();
    const abort=new AbortController();controller.current=abort;
    setSlots(Object.fromEntries(selected.map(a=>[a,{loading:true}])));
    await Promise.all(selected.map(async arm=>{
      let value:Slot;
      try{value={result:await request<Result>('/api/cases/'+item.case_id+'/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({strategy:arm}),signal:abort.signal})}}
      catch(err){value={error:err instanceof Error?err.message:'API 连接失败'}}
      if(!abort.signal.aborted)setSlots(prev=>({...prev,[arm]:value}));
    }));
  };
  const busy=Object.values(slots).some(s=>s.loading);
  return <><section className="offer"><small>{item.case_id} · 2026 Black Friday</small><h2>{item.brand}</h2><p>{item.offer}</p></section>
    <fieldset disabled={busy}><legend>选择查询策略</legend>{arms.map(a=><label key={a}><input type="checkbox" checked={selected.includes(a)} disabled={a==='C'&&!cat.llm_available} onChange={()=>select(prev=>prev.includes(a)?prev.filter(x=>x!==a):[...prev,a])}/>{names[a]}</label>)}<button disabled={busy||!selected.length} onClick={run}>{busy?'运行中…':'运行对照 →'}</button></fieldset>
    <div className="grid">{arms.map(a=><Card key={a} arm={a} state={slots[a]||{}} unavailable={a==='C'&&!cat.llm_available?cat.availability_reason:null}/>)}</div></>
}
export default function Page(){
  const [cat,setCat]=useState<Catalogue|null>(null),[id,setId]=useState('BF26-02'),[error,setError]=useState(''),[attempt,retry]=useState(0);
  useEffect(()=>{const ctl=new AbortController();setError('');request<Catalogue>('/api/cases',{signal:ctl.signal}).then(setCat).catch(()=>{if(!ctl.signal.aborted)setError('无法读取案例，请检查本地 API 服务。')});return ()=>ctl.abort()},[attempt]);
  const item=cat?.cases.find(c=>c.case_id===id);
  return <main><nav>DFO <span>HOME­BUSH</span><small>悉尼 · 2026.11.26</small></nav><h1>优惠核对工作台</h1>
   {error?<p role="alert">{error} <button onClick={()=>retry(attempt+1)}>重试</button></p>:!cat?<p role="status">正在读取案例…</p>:<><label className="picker">优惠案例 <select value={id} onChange={e=>setId(e.target.value)}>{cat.cases.map(c=><option key={c.case_id} value={c.case_id}>{c.brand} · {c.case_id}</option>)}</select></label>{item&&<Comparison key={id} item={item} cat={cat}/>}</>}
  </main>
}
