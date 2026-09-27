import React, {useEffect, useMemo, useRef, useState, createContext, useContext} from 'react';
import {createRoot} from 'react-dom/client';
import {ReactFlow, ReactFlowProvider, Handle, Position, Background, Controls, applyNodeChanges, useReactFlow} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './style.css';
import './forms.css';
import {putOperation, projectedValue, inputValue} from './state.mjs';

const EditorContext = createContext(null);
const root = createRoot(document.getElementById('root'));
let origin;
function send(type, extra={}) { if(origin) window.parent.postMessage({isStreamlitMessage:true,type,...extra},origin); }
function Field({node, field}) {
  const context = useContext(EditorContext);
  const {operations, edit} = context;
  const readonly = context.readonly || operations.some(op=>op.node===node&&op.op==='config_json');
  const value = projectedValue(field, operations, node);
  const change = value => edit({op:'value',node,path:field.path,value});
  return <label className="field"><span>{field.label}</span>{field.kind === 'boolean'
    ? <select aria-label={field.label} value={String(value)} disabled={readonly} onChange={e=>change(e.target.value==='true')}><option value="true">Sim</option><option value="false">Não</option></select>
    : <input aria-label={field.label} disabled={readonly} type={['number','integer'].includes(field.kind)?'number':'text'} step={field.kind==='integer'?'1':'any'} value={value} onChange={e=>change(inputValue(field.kind,e.target.value))}/>}</label>;
}
function FlowNode({id,data,selected}) {
  const {select, readonly} = useContext(EditorContext);
  return <article className={`flow-node ${selected?'active':''}`}>
    <Handle type="target" position={Position.Left} id="execution-in" aria-label={`Entrada de execução de ${data.label}`}/>
    <button className="node-title nodrag" onClick={()=>select(id)}><span className="service-icon">{data.action.split('.')[0].slice(0,2).toUpperCase()}</span><span><strong>{data.label}</strong><small>{data.action}</small></span></button>
    {selected && <div className="node-fields nodrag nowheel">{data.fields.slice(0,2).map(f=><Field key={JSON.stringify(f.path)} node={id} field={f}/>)}<button className="text-button" onClick={()=>select(id)}>Configurar no painel →</button></div>}
    <div className="ports"><div className="port-column"><strong>Entradas de dados</strong>{data.targets.slice(0,4).map(port=><div className="port" key={port.path}><Handle type="target" position={Position.Left} id={'data:'+port.path} aria-label={'Preencher '+port.path}/>{port.path.split('.').at(-1)} <small>{port.type==='any'?'?':port.type}</small></div>)}</div><div className="port-column"><strong>Saídas de dados</strong>{data.outputs.slice(0,4).map(port=><div className="port output" key={port.path}><Handle type="source" position={Position.Right} id={'data:'+port.path} aria-label={'Usar '+port.path}/>{port.path.split('.').at(-1)} <small>{port.type==='any'?'?':port.type}</small></div>)}</div></div>
    <footer>{data.fields.length} campos · {readonly?'Somente leitura':'Configuração visual'}</footer>
    <Handle type="source" position={Position.Right} id="execution-out" aria-label={`Saída de execução de ${data.label}`}/>
  </article>;
}
const nodeTypes = {flowops:FlowNode};
function Editor({data,theme}) {
  const flow = useReactFlow();
  const [selected,setSelected] = useState(data.nodes.find(n=>!n.data.action.startsWith('core.'))?.id || data.nodes[0]?.id);
  const [operations,setOperations] = useState(data.pending?.operations || []);
  const [base,setBase] = useState(data.pending?.base || data.base);
  const [nodes,setNodes] = useState(data.nodes);
  const [search,setSearch] = useState('');
  const [panel,setPanel] = useState('Configurar');
  const [codeEditing,setCodeEditing] = useState(false);
  const [left,setLeft] = useState('Etapas');
  const [source,setSource] = useState('');
  const [target,setTarget] = useState('');
  const [destination,setDestination] = useState('');
  const [branch,setBranch] = useState('default');
  const [connectionError,setConnectionError] = useState('');
  const counter=useRef(0);
  const dataRef=useRef(data); dataRef.current=data;
  const pendingRef=useRef(operations); pendingRef.current=operations;
  const notify=(kind,ops=operations,selection=null)=>send('streamlit:setComponentValue',{value:{protocol:1,book_id:data.book_id,revision:data.revision,base,event_id:`${Date.now()}-${++counter.current}`,kind,operations:ops,selected:selection},dataType:'json'});
  useEffect(()=>{
    setNodes(data.nodes);
    if(!data.pending){setOperations([]);setBase(data.base);}
    else if(!pendingRef.current.length){setOperations(data.pending.operations);setBase(data.pending.base);}
  },[data.base]);
  useEffect(()=>{const surface=document.querySelector('.workbench'); const observer=new ResizeObserver(()=>send('streamlit:setFrameHeight',{height:Math.ceil(surface.getBoundingClientRect().height)+2})); observer.observe(surface); return ()=>observer.disconnect();},[]);
  const readonly=data.readonly;
  const edit=operation=>{if(readonly)return;const next=putOperation(pendingRef.current,operation);if(next.length>100)return;pendingRef.current=next;setOperations(next);notify('draft',next);};
  const select=id=>{setSelected(id);setSource('');setTarget('');setCodeEditing(false);const node=data.nodes.find(n=>n.id===id);setBranch(node?.data.branches[0]||'default');if(node)flow.setCenter(node.position.x+122,node.position.y+90,{zoom:.8,duration:200});};
  const chosen=data.nodes.find(n=>n.id===selected);
  const end=data.nodes.find(n=>n.data.action==='core.end');
  const conflict=base!==data.base && operations.length>0;
  const shown=useMemo(()=>nodes.map(node=>({...node, selected:node.id===selected, data:{...node.data,label:operations.findLast(op=>op.op==='label'&&op.node===node.id)?.value??node.data.label}})),[nodes,selected,operations]);
  const edges=data.edges.map(edge=>({...edge,type:'smoothstep',label:({default:'Continuar',true:'Verdadeiro',false:'Falso',failure:'Falha'})[edge.label]||edge.label,style:{stroke:'#8898ac',strokeWidth:1.8}}));
  edges.push(...(data.data_edges||[]).map(edge=>({...edge,type:'smoothstep',style:{stroke:'#258268',strokeDasharray:'5 4',strokeWidth:1.5}})));
  const connectPorts=c=>{setConnectionError('');const fromData=c.sourceHandle?.startsWith('data:');const toData=c.targetHandle?.startsWith('data:');if(fromData!==toData){setConnectionError('Conecte saída de dados a entrada de dados, ou saída de execução a entrada de execução.');return;}edit(fromData?{op:'bind',node:c.target,source:c.sourceHandle.slice(5),target:c.targetHandle.slice(5)}:{op:'connect',node:c.source,target:c.target,branch:'default'});};
  const style=theme?.base==='dark'?{'--shell':'#141820','--surface':'#1b2029','--canvas':'#11151c','--text':'#e8edf5','--muted':'#a4afbf','--border':'#323b49','--accent':'#f7cc56','--tint':'#332e20'}:{};
  return <EditorContext.Provider value={{operations,edit,readonly,select}}><main className="workbench" style={style}>
    <header className="topbar"><div className="brand-mark">F</div><div className="title"><small>FLOWOPS / CRIAR E EDITAR</small><h1>{data.name}</h1></div><span className={`status ${operations.length?'pending':''}`}>{operations.length?`${operations.length} alterações pendentes`:`Rascunho · revisão ${data.revision}`}</span><button disabled={readonly||!operations.length} onClick={()=>{setOperations([]);setBase(data.base);notify('discard',[]);}}>Descartar</button><button className="primary" disabled={readonly||!operations.length||conflict} onClick={()=>notify('apply')}>Aplicar ao rascunho</button></header>
    {conflict&&<div className="notice" role="alert">O rascunho mudou em outra visão. As edições deste canvas estão preservadas. Compare e descarte explicitamente antes de editar a revisão atual.</div>}
    {connectionError&&<div className="notice" role="alert">{connectionError}</div>}
    <div className="workspace-grid">
      <aside className="explorer"><div className="tabs" aria-label="Painel de navegação">{['Etapas','Biblioteca'].map(tab=><button key={tab} aria-pressed={left===tab} onClick={()=>setLeft(tab)}>{tab}</button>)}</div><label className="search"><span>Buscar {left.toLowerCase()}</span><input aria-label="Buscar no painel" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Nome ou serviço…"/></label>
        <div className="explorer-list">{left==='Etapas'?data.nodes.filter(n=>(n.data.label+n.data.action).toLowerCase().includes(search.toLowerCase())).map((node,index)=><button className={`step ${node.id===selected?'selected':''}`} key={node.id} onClick={()=>select(node.id)}><span className="step-number">{String(index+1).padStart(2,'0')}</span><span>{node.data.label}<small>{node.data.action}</small></span></button>):data.actions.filter(a=>(a.id+a.label).toLowerCase().includes(search.toLowerCase())).map(action=><button className="step" key={action.id} disabled={readonly||!end} onClick={()=>edit({op:'add',node:end.id,value:action.id})}><span>＋</span><span>{action.label}<small>Inserir antes do fim</small></span></button>)}</div><footer>Aplicar mantém a edição nesta sessão. Salvar e publicar estão na revisão do procedimento.</footer></aside>
      <section className="canvas-surface" aria-label="Área visual do fluxo"><div className="canvas-heading"><span>Fluxo</span><small>{data.nodes.length} etapas · {data.edges.length} conexões</small></div><div className="graph"><ReactFlow nodes={shown} edges={edges} nodeTypes={nodeTypes} onNodesChange={changes=>setNodes(ns=>applyNodeChanges(changes,ns))} onNodeClick={(_,n)=>select(n.id)} onNodeDragStop={(_,n)=>edit({op:'position',node:n.id,value:[n.position.x,n.position.y]})} onConnect={connectPorts} nodesDraggable={!readonly} nodesConnectable={!readonly} edgesReconnectable={false} deleteKeyCode={null} minZoom={0.15} maxZoom={1.5} fitView fitViewOptions={{padding:0.15}} ariaLabelConfig={{'controls.zoomIn.ariaLabel':'Ampliar','controls.zoomOut.ariaLabel':'Reduzir','controls.fitView.ariaLabel':'Enquadrar fluxo','controls.interactive.ariaLabel':'Alternar interação','node.a11yDescription.default':'Selecione uma etapa para configurar no painel.','edge.a11yDescription.default':'Conexão entre etapas.'}}><Background color="#bac5d4" gap={24} size={1}/><Controls showInteractive={false}/></ReactFlow></div><div className="canvas-note">Selecione uma etapa para configurar · Use o painel para conectar sem arrastar</div></section>
      <aside className="inspector" aria-label="Configuração contextual"><header><small>ETAPA SELECIONADA</small><h2>{chosen?.data.label||'Selecione uma etapa'}</h2><p>{chosen?.data.action}</p></header><div className="tabs">{['Configurar','Conectar','Código'].map(tab=><button key={tab} aria-pressed={panel===tab} onClick={()=>setPanel(tab)}>{tab}</button>)}</div>
        <div className="inspector-content">{chosen&&panel==='Configurar'&&<><label className="field"><span>Nome da etapa</span><input aria-label="Nome da etapa no canvas" value={operations.findLast(op=>op.op==='label'&&op.node===selected)?.value??chosen.data.label} disabled={readonly} onChange={e=>edit({op:'label',node:selected,value:e.target.value})}/></label><p className="help">Edite os valores existentes. Objetos, listas, tipos e consultas têm controles adicionais em Configuração completa.</p>{chosen.data.fields.map(field=><Field key={JSON.stringify(field.path)} node={selected} field={field}/>)}<button onClick={()=>notify('select',operations,selected)}>Configuração completa</button><button className="danger" disabled={readonly||['core.start','core.end'].includes(chosen.data.action)} onClick={()=>edit({op:'remove',node:selected})}>Preparar remoção da etapa</button></>}
        {chosen&&panel==='Conectar'&&<><h3>Origem de um valor</h3><p className="help">Use a saída de uma etapa anterior ou um parâmetro para preencher um campo. Isso não cria uma conexão de execução.</p><label className="field"><span>Origem dos dados</span><select aria-label="Origem dos dados" value={source} onChange={e=>setSource(e.target.value)} disabled={readonly}><option value="">Selecionar origem</option>{chosen.data.sources.map(s=><option key={s.path} value={s.path}>{s.label}</option>)}</select></label><label className="field"><span>Campo de destino</span><select aria-label="Campo de destino" value={target} onChange={e=>setTarget(e.target.value)} disabled={readonly}><option value="">Selecionar campo</option>{chosen.data.targets.map(t=><option key={t.path} value={t.path}>{t.path} · {t.type}</option>)}</select></label><button disabled={readonly||!source||!target} onClick={()=>edit({op:'bind',node:selected,source,target})}>Preparar vínculo de dados</button><hr/><h3>Próxima etapa</h3><label className="field"><span>Destino da execução</span><select aria-label="Destino da execução" value={destination} onChange={e=>setDestination(e.target.value)}><option value="">Selecionar etapa</option>{data.nodes.filter(n=>n.id!==selected).map(n=><option key={n.id} value={n.id}>{n.data.label}</option>)}</select></label><label className="field"><span>Ramo</span><select aria-label="Ramo da execução" value={branch} onChange={e=>setBranch(e.target.value)}>{chosen.data.branches.map(value=><option key={value} value={value}>{({default:'Continuar',true:'Verdadeiro',false:'Falso',failure:'Falha'})[value]||value}</option>)}</select></label><button disabled={readonly||!destination} onClick={()=>edit({op:'connect',node:selected,target:destination,branch})}>Preparar conexão</button>{data.edges.filter(e=>e.source===selected).map(e=><button className="text-button" key={e.id} disabled={readonly} onClick={()=>edit({op:'disconnect',node:selected,target:e.target,branch:e.label})}>Remover ligação → {data.nodes.find(n=>n.id===e.target)?.data.label} ({e.label})</button>)}</>}
        {chosen&&panel==='Código'&&<><p className="help">Definição da etapa em JSON. O texto é aplicado somente ao confirmar. Se estiver inválido, ele permanece preservado e a visão visual continua mostrando a configuração anterior.</p>{codeEditing||operations.some(op=>op.op==='config_json'&&op.node===selected)?<textarea aria-label="Editar JSON da etapa" rows={20} disabled={readonly} value={operations.findLast(op=>op.op==='config_json'&&op.node===selected)?.value??chosen.data.config_json} onChange={e=>edit({op:'config_json',node:selected,value:e.target.value})}/>:<><pre>{chosen.data.config_json}</pre><button disabled={readonly||operations.length>0} onClick={()=>setCodeEditing(true)}>Editar JSON</button></>}<details><summary>Ver alterações preparadas</summary><pre>{JSON.stringify(operations.filter(op=>op.node===selected),null,2)}</pre></details></>}</div>
      </aside>
    </div><footer className="statusbar"><span>● {readonly?'Somente leitura':'Edição local'}</span><span>Execução e aprovações pelo motor do FlowOps</span><span>Visual / JSON</span></footer>
  </main></EditorContext.Provider>;
}
window.addEventListener('message',event=>{if(event.source!==window.parent||event.data?.type!=='streamlit:render')return;origin=event.origin;root.render(<ReactFlowProvider><Editor data={event.data.args.data} theme={event.data.theme}/></ReactFlowProvider>);});
// The parent frame origin is provided by the browser, never by an incoming payload.
const parentOrigin=document.referrer?new URL(document.referrer).origin:window.location.origin;
origin=parentOrigin;
send('streamlit:componentReady',{apiVersion:1});
