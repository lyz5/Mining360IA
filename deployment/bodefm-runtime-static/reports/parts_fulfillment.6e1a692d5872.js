(() => {
  'use strict';
  const root = document.querySelector('[data-parts-fulfillment]');
  if (!root) return;
  const $ = s => root.querySelector(s);
  const $$ = s => [...root.querySelectorAll(s)];
  const colors = {orders:'#005B9F',current:'#119342',last:'#FFB800',older:'#E63038',unallocated:'#929CAB',future:'#7955C7'};
  const labels = {orders:'New Orders (received)',current:'Current Month',last:'Last Month',older:'2+ Months',unallocated:'Unallocated',future:'Future Order'};
  const explanations = {current:'Orders from the accounting month',last:'Orders from the previous month',older:'Orders from at least two months earlier',unallocated:'No usable unique, dated order allocation',future:'Order month is after the accounting month'};
  const cohorts = ['current','last','older','unallocated','future'];
  let locale = root.dataset.numberLocale || 'en-GB';
  try { new Intl.NumberFormat(locale); } catch (_) { locale = 'en-GB'; }
  const exact = new Intl.NumberFormat(locale,{style:'currency',currency:'EUR',minimumFractionDigits:2,maximumFractionDigits:2});
  const percent = new Intl.NumberFormat(locale,{maximumFractionDigits:2});
  const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v)) ? Number(v) : null;
  const eur = v => number(v) === null ? 'N/A' : exact.format(Number(v));
  const compact = v => {
    const n=number(v); if(n===null) return 'N/A';
    const unit=Math.abs(n)>=1e6?1e6:Math.abs(n)>=1e3?1e3:1;
    return `${new Intl.NumberFormat(locale,{maximumFractionDigits:unit===1?0:2}).format(n/unit)}${unit===1e6?' M€':unit===1e3?' K€':' €'}`;
  };
  const monthLabel = m => new Intl.DateTimeFormat(locale,{month:'short',year:'numeric'}).format(new Date(`${m}-01T12:00:00`));
  const dateLabel = d => d ? new Intl.DateTimeFormat(locale,{day:'2-digit',month:'short',year:'numeric'}).format(new Date(`${d.slice(0,10)}T12:00:00`)) : '—';
  const state={data:null, summaryController:null,detailController:null,summaryRequest:0,detailRequest:0,detailMonth:null,cohort:'',page:1,pages:1,searchTimer:null,detailTotal:null,detailSearch:''};
  const show = (selector,value) => {$(selector).hidden=!value;};
  const visualCopies=[];
  function setCopyReady(group,ready) {
    visualCopies.filter(entry=>entry.group===group).forEach(entry=>{
      entry.target.dataset.exportReady=String(ready);
      if(!entry.button.hasAttribute('aria-busy'))entry.button.disabled=!ready;
      const month=group==='detail'?state.detailMonth:state.data?.selected_month;
      entry.options.fileName=`Mining360_Parts_${entry.name}_${month||''}${group==='detail'?`_${$('[data-detail-cohort]').value||'all'}_page_${state.page}`:''}`;
    });
  }
  function prepareVisualClone(clone) {
    // The page's symbol sprite is outside each card. Inline these SVG paths so
    // icons survive the existing shared PNG renderer's standalone SVG document.
    clone.querySelectorAll('svg use').forEach(use=>{
      const href=use.getAttribute('href')||use.getAttribute('xlink:href');
      if(!href?.startsWith('#'))return;
      const symbol=document.getElementById(href.slice(1)),svg=use.closest('svg');
      if(!symbol||!svg)return;
      if(symbol.hasAttribute('viewBox'))svg.setAttribute('viewBox',symbol.getAttribute('viewBox'));
      use.replaceWith(...[...symbol.children].map(node=>node.cloneNode(true)));
    });
    const detailContext=clone.querySelector('[data-detail-context]');
    if(detailContext){
      const search=state.detailSearch;
      if(search)detailContext.textContent+=` · Search: ${search}`;
    }
  }
  function initializeVisualCopies() {
    const exporter=window.Mining360VisualExport;
    if(!exporter)return;
    const visuals=[['.pf-kpi:first-child','New_Orders','summary'],['.pf-kpi:nth-child(2)','Accounting_Sales','summary'],
      ['.pf-origin','Sales_Origin','summary'],['.pf-trend','Orders_vs_Sales','summary'],['[data-detail-panel]','Cohort_Details','detail']];
    visuals.forEach(([selector,name,group])=>{
      const target=$(selector);if(!target)return;
      const button=document.createElement('button');
      button.type='button';button.className='m360-visual-copy';button.textContent='Copy visual';
      button.dataset.exportIgnore='true';button.dataset.pfCopy=name;button.disabled=true;
      button.title='Copy this visual as a PNG image';
      button.setAttribute('aria-label',`Copy ${target.querySelector('h2')?.textContent.trim()||name} as an image`);
      target.classList.add('m360-copy-surface');target.dataset.exportReady='false';target.append(button);
      const options={button,target,fileName:`Mining360_Parts_${name}`,background:'#ffffff',scale:2,
        canCopy:()=>target.dataset.exportReady==='true'&&!target.closest('[hidden]')&&Boolean(target.getClientRects().length),
        prepareClone:prepareVisualClone,
        onFallback:()=>{
          const notice=document.querySelector('[data-visual-export-notice]');if(!notice)return;
          notice.classList.remove('is-error');notice.setAttribute('role','status');notice.textContent='PNG downloaded.';
          setTimeout(()=>notice.remove(),2000);
        }};
      exporter.bindCopyAction(options);visualCopies.push({target,button,name,group,options});
    });
  }

  async function read(url, params, controller) {
    const timeout=setTimeout(()=>controller.abort('timeout'),60000);
    try {
      const response=await fetch(`${url}?${params}`,{signal:controller.signal,credentials:'same-origin',headers:{Accept:'application/json'}});
      if(!response.headers.get('content-type')?.includes('application/json')) throw new Error('Your session may have expired. Sign in and retry.');
      const data=await response.json();
      if(!response.ok || data.ready===false) throw new Error(data.message || 'Data unavailable for this account.');
      return data;
    } finally {clearTimeout(timeout);}
  }

  async function loadSummary(month='') {
    setCopyReady('summary',false);setCopyReady('detail',false);
    clearTimeout(state.searchTimer);
    state.summaryController?.abort(); state.detailController?.abort();
    const controller=new AbortController();state.summaryController=controller;
    const request=++state.summaryRequest;
    show('[data-loading]',true); show('[data-error]',false);show('[data-empty]',false);show('[data-content]',false);show('[data-detail-panel]',false);show('[data-order-note]',false);
    $('[data-month]').disabled=true;root.setAttribute('aria-busy','true');
    if(!state.data?.months?.length)$('[data-month]').innerHTML='<option value="">Loading months…</option>';
    try {
      const data=await read(root.dataset.summaryUrl,new URLSearchParams(month?{month}:{}),controller);
      if(request!==state.summaryRequest)return;
      state.data=data;
      $('[data-month]').innerHTML=(data.months||[]).map(m=>`<option value="${esc(m)}">${esc(monthLabel(m))}</option>`).join('')||'<option value="">No available month</option>';
      if(data.selected_month)$('[data-month]').value=data.selected_month;
      $('[data-month]').disabled=!data.months?.length;
      if(data.empty){show('[data-empty]',true);$('[data-empty-message]').textContent=data.message;return;}
      const url=new URL(location.href);url.searchParams.set('month',data.selected_month);history.replaceState({},'',url);
      render(data);show('[data-content]',true);setCopyReady('summary',true);
    } catch(error) {
      if(controller.signal.aborted && controller.signal.reason!=='timeout')return;
      if(request!==state.summaryRequest)return;
      $('[data-error-message]').textContent=controller.signal.reason==='timeout'?'The source did not respond in time. Please retry.':error.message;
      if(!state.data?.months?.length)$('[data-month]').innerHTML='<option value="">Unavailable</option>';
      show('[data-error]',true);
    } finally {
      if(request===state.summaryRequest){show('[data-loading]',false);root.removeAttribute('aria-busy');if(state.data?.months?.length)$('[data-month]').disabled=false;}
    }
  }

  function render(data) {
    const k=data.kpis;
    $$('[data-kpi]').forEach(n=>{n.textContent=compact(k[n.dataset.kpi]);n.title=eur(k[n.dataset.kpi]);});
    for(const key of ['orders','sales']){
      const node=$(`[data-change="${key}"]`), change=data.changes[key];
      const p=number(change.percent);node.className=`pf-change${p===null?'':p>=0?' positive':' negative'}`;
      node.textContent=p===null?'N/A · month comparison':`${p>0?'+':''}${percent.format(p)}% vs Last Month`;
      node.title=change.reason||'Compared with the full preceding calendar month.';
    }
    $('[data-period-note]').textContent=`${monthLabel(data.selected_month)} · ${data.month_to_date?'Month to date':'Calendar month'} · EUR`;
    $('[data-freshness]').textContent=data.source.coverage?`Accounting entries through ${dateLabel(data.source.coverage)} · Order coverage not supplied`:'Source coverage date not supplied';
    const refreshDate=data.source.last_refresh?new Date(data.source.last_refresh):null;
    const refreshed=refreshDate&&Number.isFinite(refreshDate.getTime())?`Source refresh completed ${new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short'}).format(refreshDate)}.`:'Refresh time not supplied by source.';
    $('[data-scope]').textContent=`${data.source.model} · ${data.source.scope}. ${data.source.scope_note} ${refreshed}`;
    $('[data-origin-subtitle]').textContent=`Accounting sales of ${compact(k.sales)}, by order month (value and share)`;
    renderBreakdown(k);
    const r=k.reconciliation;
    $('[data-reconciliation]').innerHTML=`<span class="pf-badge ${r.status==='reconciled'?'':'warning'}" title="Source reconciliation difference: ${esc(eur(r.difference))}; rounded component difference: ${esc(eur(r.arithmetic_difference))}">${esc(r.label)}</span>`;
    renderChart(data.series);
    $('[data-trend-period]').textContent=`${monthLabel(data.series[0].month)} — ${monthLabel(data.selected_month)} · up to 12 calendar months`;
  }

  const share = (v,total) => number(v)!==null && number(total)>0 ? `${percent.format(Number(v)/Number(total)*100)}%` : 'N/A';
  function renderBreakdown(k) {
    const visible=cohorts.filter(c=>number(k[c])!==0 || number(k[c])===null);
    const signed=cohorts.some(c=>number(k[c])<0) || number(k.sales)<=0;
    const complete=cohorts.every(c=>number(k[c])!==null);
    if(signed || !complete || k.reconciliation.status!=='reconciled'){
      $('[data-breakdown]').innerHTML=`<table class="pf-signed-table"><caption>${signed?'Signed accounting sales':'Source allocation controls'}</caption><thead><tr><th>Cohort</th><th>EUR</th><th>Share of sales</th></tr></thead><tbody>${visible.map(c=>`<tr><td>${labels[c]}</td><td>${esc(eur(k[c]))}</td><td>${esc(share(k[c],k.sales))}</td></tr>`).join('')}</tbody></table>`;
    }else{
      $('[data-breakdown]').innerHTML=`<div class="pf-segments" aria-label="Sales by order cohort">${visible.map(c=>{
        const p=Number(k[c])/Number(k.sales)*100;
        return `<button class="pf-segment" data-open-cohort="${c}" data-cohort="${c}" style="width:${p}%;--cohort-color:${colors[c]}" title="${labels[c]}: ${esc(eur(k[c]))} (${esc(share(k[c],k.sales))})" aria-label="${labels[c]}: ${esc(eur(k[c]))}, ${esc(share(k[c],k.sales))}. Open details.">${p>=14?`<span>${esc(compact(k[c]))}</span><small>${esc(share(k[c],k.sales))}</small>`:''}</button>`;
      }).join('')}</div>`;
    }
    $('[data-origin-legend]').innerHTML=visible.map(c=>`<button type="button" class="pf-legend-item" data-open-cohort="${c}" title="${esc(explanations[c])}"><span class="pf-dot" style="--cohort-color:${colors[c]}"></span><span><strong>${labels[c]}</strong><small>${esc(eur(k[c]))} · ${esc(share(k[c],k.sales))}</small></span></button>`).join('');
  }

  function renderChart(series) {
    const width=1200,height=475,left=90,right=25,top=34,bottom=64,plotW=width-left-right,plotH=height-top-bottom;
    const stackOrder=['older','last','current','unallocated','future'];
    let low=0,high=0;
    series.forEach(r=>{const pos=cohorts.reduce((s,c)=>s+Math.max(number(r[c])||0,0),0),neg=cohorts.reduce((s,c)=>s+Math.min(number(r[c])||0,0),0);high=Math.max(high,pos,number(r.orders)||0);low=Math.min(low,neg,number(r.orders)||0);});
    if(high===low){high=1;}
    const unit=Math.max(high,Math.abs(low))>=1e6?1e6:Math.max(high,Math.abs(low))>=1e3?1e3:1;
    const suffix=unit===1e6?'M':unit===1e3?'K':'€';
    const span=high-low,rawStep=span/5,power=10**Math.floor(Math.log10(rawStep));
    const step=[1,2,2.5,5,10].find(n=>n*power>=rawStep)*power;
    high=Math.ceil((high+span*.06)/step)*step;
    low=low<0?Math.floor((low-span*.04)/step)*step:0;
    const y=n=>top+(high-n)/(high-low)*plotH;
    const zero=y(0),groupW=plotW/series.length,barW=Math.min(80,groupW*.37),gap=Math.min(8,groupW*.055);
    const digits=barW>=55?1:0;
    const barNumber=n=>{
      if(n!==0&&Math.abs(n)<unit/100)return compact(n);
      const precision=Math.abs(n/unit)<.1?2:Math.abs(n/unit)<1?1:digits;
      return `${new Intl.NumberFormat(locale,{maximumFractionDigits:precision}).format(n/unit)} ${suffix}`;
    };
    const axis=new Intl.NumberFormat(locale,{maximumFractionDigits:Math.max(0,-Math.floor(Math.log10(step/unit)))});
    const labelSize=series.length>9?12:16,segmentSize=barW>=55?17:12;
    let svg=`<svg viewBox="0 0 ${width} ${height}" role="group" aria-labelledby="pf-chart-title pf-chart-desc"><title id="pf-chart-title">Orders vs. Sales Trend</title><desc id="pf-chart-desc">Two columns for every available month: blue new orders on the left; accounting sales stacked by order cohort on the right. Older orders are red at the bottom, last month is yellow, and current month is green. Negative values extend below zero. Labels select months; segments open detail. Exact EUR values are available on each bar.</desc><defs><linearGradient id="pf-orders-gradient" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#005B9F"/><stop offset="1" stop-color="#08477A"/></linearGradient></defs>`;
    for(let i=0;i<=Math.round((high-low)/step);i++){const value=low+step*i,py=y(value);svg+=`<line x1="${left}" x2="${width-right}" y1="${py}" y2="${py}" class="pf-grid-line"/><text x="${left-13}" y="${py+5}" text-anchor="end" class="pf-axis-tick">${esc(axis.format(value/unit))}</text>`;}
    svg+=`<text transform="translate(24 ${(top+height-bottom)/2}) rotate(-90)" text-anchor="middle" class="pf-axis-title">Value (${suffix==='€'?'EUR':suffix+'€'})</text><line x1="${left}" x2="${left}" y1="${top}" y2="${height-bottom}" class="pf-axis-line"/><line x1="${left}" x2="${width-right}" y1="${zero}" y2="${zero}" class="pf-axis-line"/>`;
    const rect=(x,value,base,color,attrs,title,rounded=false)=>{const a=y(base),b=y(base+value),h=Math.abs(a-b);return `<rect x="${x}" y="${Math.min(a,b)}" width="${barW}" height="${h}" fill="${color}" rx="${rounded?5:0}" tabindex="0" role="button" ${attrs} aria-label="${esc(title)}"><title>${esc(title)}</title></rect>`;};
    series.forEach((r,i)=>{
      const center=left+groupW*(i+.5),xOrder=center-gap/2-barW,xSales=center+gap/2;
      const order=number(r.orders),month=r.month;
      if(order!==null){svg+=rect(xOrder,order,0,'url(#pf-orders-gradient)',`data-chart-orders="${month}"`,`${monthLabel(month)}, Order Intake: ${eur(order)}. Order details unavailable.`,true);svg+=`<text x="${xOrder+barW/2}" y="${order>=0?y(order)-10:y(order)+19}" text-anchor="middle" class="pf-bar-total" font-size="${labelSize}">${esc(barNumber(order))}</text>`;}
      let pos=0,neg=0;
      stackOrder.forEach(c=>{
        const n=number(r[c]);if(n===null||n===0)return;
        const base=n>=0?pos:neg;
        svg+=rect(xSales,n,base,colors[c],`data-chart-cohort="${c}" data-chart-month="${month}"`,`${monthLabel(month)}, ${labels[c]}: ${eur(n)}. Open details.`);
        const h=Math.abs(y(base+n)-y(base)),text=barNumber(n),fontSize=Math.min(segmentSize,Math.floor(h-4));
        if(fontSize>=11&&barW>=30)svg+=`<text pointer-events="none" x="${xSales+barW/2}" y="${(y(base)+y(base+n))/2}" dy=".35em" text-anchor="middle" class="pf-segment-value" font-size="${fontSize}" fill="${c==='last'?'#13233b':'white'}">${esc(text)}</text>`;
        if(n>=0)pos+=n;else neg+=n;
      });
      if(cohorts.every(c=>number(r[c])!==null))svg+=`<text x="${xSales+barW/2}" y="${y(pos)-10}" text-anchor="middle" class="pf-bar-total" font-size="${labelSize}"><title>Accounting sales total: ${esc(eur(r.sales))}</title>${esc(barNumber(Number(r.sales)))}${neg<0?' net':''}</text>`;
      svg+=`<text x="${center}" y="${height-27}" text-anchor="middle" class="pf-month-tick" tabindex="0" role="button" data-select-month="${month}" aria-label="Select ${esc(monthLabel(month))}">${esc(monthLabel(month))}</text>`;
    });
    svg+='</svg>';$('[data-chart]').innerHTML=svg;
    const legend=['orders',...cohorts.filter(c=>c!=='future'&&(c!=='unallocated'||series.some(r=>number(r[c])!==null&&number(r[c])!==0)))];
    $('[data-chart-legend]').innerHTML=legend.map(c=>`<span><i class="pf-dot" style="--cohort-color:${colors[c]}"></i>${c==='orders'?labels[c]:'Sales — '+labels[c]}</span>`).join('');
  }

  function openOrders(month=state.data?.selected_month) {
    show('[data-order-note]',true);$('[data-order-note] p').textContent=`${monthLabel(month)}: Order Intake is available as a model measure. A verified order-level detail source has not been exposed for this page. Accounting allocations cannot substitute for new orders.`;
    $('[data-order-note]').scrollIntoView({behavior:'smooth',block:'center'});
  }
  function openDetails(month,cohort=''){
    state.detailMonth=month;state.cohort=cohort;state.page=1;
    $('[data-detail-cohort]').value=cohort;$('[data-detail-search]').value='';
    show('[data-detail-panel]',true);$('[data-detail-panel]').focus({preventScroll:true});
    $('[data-detail-panel]').scrollIntoView({behavior:'smooth',block:'start'});loadDetails();
  }
  function detailParams(){return new URLSearchParams({month:state.detailMonth,cohort:$('[data-detail-cohort]').value,search:$('[data-detail-search]').value,sort:$('[data-detail-sort]').value,direction:$('[data-detail-direction]').value,page:state.page});}
  async function loadDetails(){
    setCopyReady('detail',false);
    state.detailController?.abort();const controller=new AbortController();state.detailController=controller;const request=++state.detailRequest;
    $('[data-detail-rows]').innerHTML='';$('[data-detail-status]').textContent='Loading accounting detail…';$('[data-detail-total]').textContent='';show('[data-detail-retry]',false);
    $('[data-detail-context]').textContent=`${monthLabel(state.detailMonth)} · ${labels[$('[data-detail-cohort]').value]||'All cohorts'}`;
    $('[data-prev]').disabled=true;$('[data-next]').disabled=true;
    try{
      const data=await read(root.dataset.detailsUrl,detailParams(),controller);if(request!==state.detailRequest)return;
      state.pages=data.pages;
      state.detailSearch=data.search||'';
      $('[data-detail-total]').textContent=`Filtered accounting total: ${eur(data.total)} · ${new Intl.NumberFormat(locale).format(data.total_rows)} rows`;
      const detailNotes={reconciled:'Detail reconciles with the source cohort measure.',warning:'Data quality warning: detail does not reconcile with the source cohort measure.',filtered:`Search subset · full cohort control: ${eur(data.control_total)}.`,unavailable:'Detail reconciliation is unavailable.'};
      $('[data-detail-status]').textContent=data.total_rows?(detailNotes[data.reconciliation]||''):'No matching accounting rows. This is an empty detail, not a source failure.';
      $('[data-detail-rows]').innerHTML=data.rows.map(row=>`<tr><td>${esc(dateLabel(row.accounting_date))}</td><td>${esc(dateLabel(row.order_date))}</td><td>${esc(row.order_key||'—')}</td><td>${esc(row.invoice_key||'—')}</td><td>${esc(row.cohort||'—')}</td><td class="pf-numeric">${esc(eur(row.amount))}</td></tr>`).join('');
      $('[data-page-label]').textContent=`Page ${data.page} of ${data.pages}`;$('[data-prev]').disabled=data.page<=1;$('[data-next]').disabled=data.page>=data.pages;
      setCopyReady('detail',true);
    }catch(error){if(controller.signal.aborted&&controller.signal.reason!=='timeout')return;if(request!==state.detailRequest)return;$('[data-detail-status]').textContent=controller.signal.reason==='timeout'?'The detail query timed out. Please retry.':error.message;show('[data-detail-retry]',true);$('[data-page-label]').textContent='';}
  }
  async function exportDetails(){
    const exportMonth=state.detailMonth;
    const button=$('[data-export]');button.disabled=true;const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),60000);
    try{
      const params=detailParams();params.delete('page');
      const response=await fetch(`${root.dataset.exportUrl}?${params}`,{signal:controller.signal,credentials:'same-origin'});
      if(!response.ok || !response.headers.get('content-type')?.includes('text/csv')){let data={};try{data=await response.json();}catch(_){}throw new Error(data.message||'Export unavailable. Sign in or refine the filter and retry.');}
      const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`parts-sales-${exportMonth}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      $('[data-detail-status]').textContent='Exported all matching rows for the announced filters.';
    }catch(error){$('[data-detail-status]').textContent=controller.signal.aborted?'Export timed out. Please retry.':error.message;}finally{clearTimeout(timeout);button.disabled=false;}
  }

  root.addEventListener('click',event=>{
    const target=event.target.closest('[data-open-cohort],[data-chart-cohort],[data-select-month],[data-chart-orders],[data-orders-open]');if(!target)return;
    if(target.hasAttribute('data-select-month'))loadSummary(target.dataset.selectMonth);
    else if(target.hasAttribute('data-chart-orders'))openOrders(target.dataset.chartOrders);
    else if(target.hasAttribute('data-orders-open'))openOrders();
    else openDetails(target.dataset.chartMonth||state.data.selected_month,target.dataset.chartCohort||target.dataset.openCohort||'');
  });
  root.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target.matches('svg [role=button]')){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
  $('[data-month]').addEventListener('change',event=>loadSummary(event.target.value));
  $('[data-refresh]').addEventListener('click',()=>loadSummary($('[data-month]').value||''));$('[data-retry]').addEventListener('click',()=>loadSummary($('[data-month]').value||''));
  $('[data-detail-close]').addEventListener('click',()=>{clearTimeout(state.searchTimer);state.detailController?.abort();setCopyReady('detail',false);show('[data-detail-panel]',false);});
  $('[data-order-close]').addEventListener('click',()=>show('[data-order-note]',false));
  ['[data-detail-cohort]','[data-detail-sort]','[data-detail-direction]'].forEach(s=>$(s).addEventListener('change',()=>{state.page=1;loadDetails();}));
  $('[data-detail-search]').addEventListener('input',()=>{setCopyReady('detail',false);clearTimeout(state.searchTimer);state.searchTimer=setTimeout(()=>{state.page=1;loadDetails();},350);});
  $('[data-prev]').addEventListener('click',()=>{if(state.page>1){state.page--;loadDetails();}});$('[data-next]').addEventListener('click',()=>{if(state.page<state.pages){state.page++;loadDetails();}});
  $('[data-detail-retry]').addEventListener('click',loadDetails);$('[data-export]')?.addEventListener('click',exportDetails);
  initializeVisualCopies();loadSummary(new URLSearchParams(location.search).get('month')||'');
})();
