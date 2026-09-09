const state={csrf:"",user:null,exchange:null};
const $=selector=>document.querySelector(selector);
const escapeHtml=value=>String(value).replace(/[&<>'"]/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
const tryMoney=value=>new Intl.NumberFormat("tr-TR",{style:"currency",currency:"TRY",maximumFractionDigits:2}).format(Number(value||0));
const percent=value=>`%${new Intl.NumberFormat("tr-TR",{maximumFractionDigits:3}).format(Number(value||0)*100)}`;

async function api(path,options={}){
  const headers={...(options.body?{"Content-Type":"application/json"}:{}),...(state.csrf?{"X-CSRF-Token":state.csrf}:{}),...options.headers};
  const response=await fetch(path,{credentials:"same-origin",...options,headers});
  if(!response.ok){let detail=`İstek başarısız (${response.status})`;try{detail=(await response.json()).detail||detail}catch{}throw new Error(detail)}
  if(response.status===204)return null;
  return response.json();
}

function renderOpportunities(payload){
  const items=payload.items||[];
  $("#pair-count").textContent=payload.common_pair_count??"—";
  $("#ready-count").textContent=items.filter(x=>x.executable).length;
  const rows=$("#opportunity-rows"); rows.textContent="";
  if(!items.length){rows.innerHTML='<tr><td colspan="6" class="empty-cell">İlk tam derinlik taraması sürüyor. Bu ekran gerçek emir göndermez.</td></tr>';return}
  for(const x of items.slice(0,12)){
    const tr=document.createElement("tr");
    tr.innerHTML=`<td><div class="pair"><span class="coin">${escapeHtml(x.pair.slice(0,2))}</span><b>${escapeHtml(x.pair)}</b></div></td>
      <td class="direction">${escapeHtml(x.buy_exchange)} <b>→</b> ${escapeHtml(x.sell_exchange)}</td>
      <td class="${x.executable?"profit":"watch"}">${percent(x.net_profit_pct)}</td>
      <td>${tryMoney(Number(x.base_amount)*Number(x.buy_vwap))}</td><td class="${Number(x.net_profit_try)>=0?"profit":"loss"}">${tryMoney(x.net_profit_try)}</td>
      <td><span class="status-pill ${x.executable?"":"observe"}">${x.executable?"PAPER UYGUN":"İZLE"}</span></td>`;
    rows.appendChild(tr);
  }
  const ok=Boolean(payload.last_success_ms),feeds=payload.market_data?.feeds||{};
  const feedState=(name)=>{const feed=feeds[name]||{};if(!feed.connected)return "Kesik";if(feed.age_ms==null)return "Bağlanıyor";return feed.age_ms<10000?`${Math.max(0,feed.age_ms)} ms`:`Eski veri · ${Math.round(feed.age_ms/1000)} sn`};
  const btOk=Boolean(feeds.btcturk?.connected&&feeds.btcturk?.age_ms<10000);
  const bnOk=Boolean(feeds.binance_tr?.connected&&feeds.binance_tr?.age_ms<10000);
  $("#scanner-health").textContent=ok&&btOk&&bnOk?"Gerçek zamanlı":ok?"REST yedekli":"Bekliyor";
  $("#scanner-age").textContent=ok?`Son hesaplama ${new Date(payload.last_success_ms).toLocaleTimeString("tr-TR")} · REST yedek ${payload.market_data?.rest_fallback_count||0}`:"Public veriler bekleniyor";
  $("#bt-health").textContent=feedState("btcturk");
  $("#bn-health").textContent=feedState("binance_tr");
  $("#scan-health").textContent=ok?"Aktif":"Başlıyor";
  const dots=document.querySelectorAll(".health-panel i");
  dots[0]?.classList.toggle("good",btOk);dots[1]?.classList.toggle("good",bnOk);dots[2]?.classList.toggle("good",ok);
}

function renderAccount(data){
  state.user=data;state.csrf=data.csrf_token;$("#current-user").textContent=data.username;
  $("#add-user-button").hidden=!data.is_admin;
  const settings=data.settings||{};
  $("#risk-active").value=String(Boolean(settings.active));
  $("#risk-max").value=settings.max_trade_try||"1000";
  $("#risk-daily").value=settings.daily_loss_limit_try||"250";
  $("#risk-recovery").value=settings.max_recovery_loss_try||"100";
  const keys=Object.fromEntries((data.credentials||[]).map(x=>[x.exchange,x]));
  for(const [exchange,id,statusId] of [["btcturk","#bt-key-state","#bt-status"],["binance_tr","#bn-key-state","#bn-status"]]){
    const item=keys[exchange];const text=!item?"Bağlı değil":item.validated_at?`Doğrulandı · ${item.key_hint}`:"Kaydedildi · doğrulama gerekli";
    $(id).textContent=text;$(statusId).textContent=text;
    $(`#account-${exchange==="btcturk"?"bt":"bn"}-summary`).textContent=text;
  }
}

function renderBalances(payload){
  const exchanges=Object.fromEntries((payload.exchanges||[]).map(item=>[item.exchange,item]));
  const tryValues={};
  for(const [exchange,id,statusId] of [["btcturk","#bt-balance","#bt-status"],["binance_tr","#bn-balance","#bn-status"]]){
    const item=exchanges[exchange]||{};
    const tryRow=(item.balances||[]).find(row=>row.asset==="TRY");
    tryValues[exchange]=Number(tryRow?.available||0);
    $(id).textContent=tryRow?tryMoney(tryRow.available):"—";
    if(item.state==="ok")$(statusId).textContent=tryRow?`TRY kullanılabilir · ${tryMoney(tryRow.available)}`:"Bakiye alındı · TRY yok";
    else if(item.state==="error")$(statusId).textContent=item.error||"Bakiye alınamadı";
    const assetTarget=$(exchange==="btcturk"?"#bt-assets":"#bn-assets");assetTarget.textContent="";
    const assets=(item.balances||[]).filter(row=>Number(row.total||0)>0).slice(0,6);
    if(!assets.length){assetTarget.innerHTML="<small>Varlık bakiyesi yok</small>"}
    else assets.forEach(row=>{const pill=document.createElement("small");pill.textContent=`${row.asset} ${row.total}`;assetTarget.appendChild(pill)});
  }
  $("#available-try").textContent=tryMoney(payload.available_try_total||0);
  const total=tryValues.btcturk+tryValues.binance_tr;
  $("#bt-bar").style.width=total?`${Math.round(tryValues.btcturk/total*100)}%`:"0%";
  $("#bn-bar").style.width=total?`${Math.round(tryValues.binance_tr/total*100)}%`:"0%";
}

function renderSummary(payload){
  const execution=payload.execution||{};
  $("#today-pnl").textContent=tryMoney(execution.today_realized_profit_try||0);
  $("#total-pnl").textContent=tryMoney(execution.realized_profit_try||0);
  $("#week-pnl").textContent=tryMoney(execution.seven_days_realized_profit_try||0);
  $("#month-pnl").textContent=tryMoney(execution.thirty_days_realized_profit_try||0);
  $("#trade-ratio").textContent=`${execution.balanced||0} / ${execution.total||0}`;
  const q=payload.qualification||{};
  $("#qualification-summary").textContent=`Gözlem ${q.observation_hours||"0"}/72 saat · fırsat ${q.paper_opportunities||0}/100 · paper işlem ${q.paper_trades||0}/20`;
}

function renderTrades(payload){
  const list=$("#trade-list");list.textContent="";
  const items=payload.items||[];
  if(!items.length){list.innerHTML='<div class="empty-state"><strong>Henüz paper işlem yok</strong><small>Motor yalnızca nitelikli fırsatları test kayıtlarına ekleyecek.</small></div>';return}
  for(const item of items.slice(0,8)){
    const row=document.createElement("div");row.className="trade-row";
    const time=item.created_at?new Date(Number(item.created_at)).toLocaleString("tr-TR"):"—";
    const pnl=item.realized_profit_try==null?"Bekliyor":tryMoney(item.realized_profit_try);
    row.innerHTML=`<div><strong>${escapeHtml(item.pair)}</strong><small>${escapeHtml(time)}</small></div>
      <div><strong>${escapeHtml(item.buy_exchange)} → ${escapeHtml(item.sell_exchange)}</strong><small>${escapeHtml(item.state)} · ${escapeHtml(item.mode)}</small></div>
      <div class="amount ${Number(item.realized_profit_try||0)<0?"loss":"profit"}"><strong>${escapeHtml(pnl)}</strong><small>Gerçekleşen net</small></div>`;
    list.appendChild(row);
  }
}

function renderHummingbotStatus(hb){
  const labels={idle:"Hazır · test", "test-ready":"Test hazır", stopped:"Durduruldu",
    "emergency-stopped":"ACİL DURDURMA", blocked:"Engellendi", "not-installed":"Kurulmadı"};
  $("#hummingbot-health").textContent=labels[hb.state]||hb.state||"Bilinmiyor";
  $("#hummingbot-note").textContent=hb.reason||"Hummingbot hostu yalnızca test kontrolü için hazırdır; canlı emir kapalıdır.";
  const emergency=hb.state==="emergency-stopped";
  document.querySelectorAll("[data-hb-action]").forEach(button=>{
    button.disabled=emergency&&button.dataset.hbAction!=="start_test";
  });
}

function renderAudit(payload){
  const list=$("#audit-list");list.textContent="";
  const items=payload.items||[];
  if(!items.length){list.innerHTML="<small>Henüz denetim kaydı yok</small>";return}
  items.slice(0,10).forEach(item=>{
    const row=document.createElement("div");row.className="audit-row";
    const when=item.created_at?new Date(Number(item.created_at)*1000).toLocaleString("tr-TR"):"—";
    row.innerHTML=`<span>${escapeHtml(when)}</span><b>${escapeHtml(item.event||"olay")}</b>`;
    list.appendChild(row);
  });
}

async function renderQualification(){
  const result=await api("/api/live/qualification");const list=$("#qualification-list");list.textContent="";
  const failures=result.failures||[],gateCount=8;$(".score").textContent=result.eligible?`${gateCount}/${gateCount}`:`${Math.max(0,gateCount-failures.length)}/${gateCount}`;
  const messages=failures.length?failures:["Bütün canlı işlem kapıları tamamlandı"];
  messages.slice(0,5).forEach(message=>{const li=document.createElement("li");li.innerHTML=`<span>${failures.length?"!":"✓"}</span><div><strong>${escapeHtml(message)}</strong><small>${failures.length?"Canlı mod kilitli":"Yerel onay gerekli"}</small></div>`;list.appendChild(li)});
  return result;
}

async function refresh(){
  try{const [me,opportunities,health,summary,history,wallets,audit]=await Promise.all([api("/api/me"),api("/api/opportunities"),api("/api/health"),api("/api/metrics/summary"),api("/api/executions?limit=20"),api("/api/balances"),api("/api/audit?limit=12")]);renderAccount(me);renderOpportunities(opportunities);renderHummingbotStatus(health.hummingbot||{});renderSummary(summary);renderTrades(history);renderBalances(wallets);renderAudit(audit);await renderQualification()}
  catch(error){if(/Oturum/.test(error.message))await openAuth();else $("#scanner-age").textContent=error.message}
}

async function openAuth(){
  const setup=await api("/api/bootstrap");$("#auth-title").textContent=setup.needs_owner?"İlk kullanıcıyı oluştur":"Oturum aç";
  $("#auth-form").dataset.endpoint=setup.needs_owner?"/api/bootstrap":"/api/login";if(!$("#auth-dialog").open)$("#auth-dialog").showModal();
}

$("#auth-form").addEventListener("submit",async event=>{event.preventDefault();$("#auth-error").textContent="";try{
  const result=await api(event.currentTarget.dataset.endpoint,{method:"POST",body:JSON.stringify({username:$("#auth-username").value,password:$("#auth-password").value})});
  state.csrf=result.csrf_token;$("#auth-dialog").close();await refresh();
}catch(error){$("#auth-error").textContent=error.message}});

document.querySelectorAll(".credential-edit").forEach(button=>button.addEventListener("click",()=>{state.exchange=button.dataset.exchange;$("#credential-title").textContent=state.exchange==="btcturk"?"BTCTürk API anahtarı":"Binance TR API anahtarı";$("#api-key").value="";$("#api-secret").value="";$("#credential-error").textContent="";$("#account-dialog").close();$("#credential-dialog").showModal()}));
$("#credential-cancel").addEventListener("click",()=>$("#credential-dialog").close());
$("#credential-form").addEventListener("submit",async event=>{event.preventDefault();$("#credential-error").textContent="";try{
  await api("/api/credentials",{method:"PUT",body:JSON.stringify({exchange:state.exchange,api_key:$("#api-key").value,api_secret:$("#api-secret").value})});
  $("#api-secret").value="";await api(`/api/credentials/${state.exchange}/test`,{method:"POST"});$("#credential-dialog").close();await refresh();
}catch(error){$("#api-secret").value="";$("#credential-error").textContent=`Anahtar kaydedildi; bağlantı testi geçmedi: ${error.message}`;await refresh()}});

$("#add-user-button").addEventListener("click",()=>{$("#account-dialog").close();$("#user-error").textContent="";$("#user-dialog").showModal()});
$("#user-cancel").addEventListener("click",()=>$("#user-dialog").close());
$("#user-form").addEventListener("submit",async event=>{event.preventDefault();$("#user-error").textContent="";try{
  await api("/api/users",{method:"POST",body:JSON.stringify({username:$("#new-username").value,password:$("#new-password").value})});
  event.currentTarget.reset();$("#user-dialog").close();
}catch(error){$("#user-error").textContent=error.message}});

document.querySelectorAll(".chip").forEach(button=>button.addEventListener("click",()=>{document.querySelectorAll(".chip").forEach(x=>x.classList.remove("active"));button.classList.add("active")}));
document.querySelectorAll("[data-view]").forEach(link=>link.addEventListener("click",()=>{
  document.querySelectorAll(".nav-item").forEach(x=>x.classList.toggle("active",x===link));
  const target=document.getElementById(link.dataset.view);target?.scrollIntoView({behavior:"smooth",block:"start"});
}));

document.querySelectorAll("[data-hb-action]").forEach(button=>button.addEventListener("click",async()=>{
  button.disabled=true;
  try{await api("/api/hummingbot/control",{method:"POST",body:JSON.stringify({action:button.dataset.hbAction})});await refresh()}
  catch(error){$("#hummingbot-note").textContent=error.message;button.disabled=false}
}));
$("#test-details")?.addEventListener("click",()=>$(".guard-card")?.scrollIntoView({behavior:"smooth",block:"center"}));
$("#mobile-more")?.addEventListener("click",()=>$("#account-dialog").showModal());

$("#risk-form")?.addEventListener("submit",async event=>{event.preventDefault();$("#risk-error").textContent="";try{
  await api("/api/settings/test",{method:"PUT",body:JSON.stringify({active:$("#risk-active").value==="true",max_trade_try:$("#risk-max").value,daily_loss_limit_try:$("#risk-daily").value,max_recovery_loss_try:$("#risk-recovery").value})});await refresh();
}catch(error){$("#risk-error").textContent=error.message}});
$("#refresh-balances")?.addEventListener("click",async()=>{try{renderBalances(await api("/api/balances"))}catch(error){$("#bt-status").textContent=error.message}});
$("#open-accounts")?.addEventListener("click",()=>$("#account-dialog").showModal());

const liveDialog=$("#live-dialog"),liveInput=$("#live-confirm"),confirmLive=$("#confirm-live"),testButton=$("#test-mode"),liveButton=$("#live-mode"),notice=$("#mode-notice");
liveButton.addEventListener("click",async()=>{const result=await renderQualification();liveInput.value="";liveInput.disabled=!result.eligible;confirmLive.disabled=true;liveDialog.showModal();if(result.eligible)liveInput.focus()});
liveInput.addEventListener("input",()=>confirmLive.disabled=liveInput.value.trim()!=="CANLI İŞLEMİ AÇ");
liveDialog.addEventListener("close",async()=>{if(liveDialog.returnValue!=="confirm"||confirmLive.disabled)return;try{await api("/api/live/enable",{method:"POST"})}catch(error){notice.innerHTML=`<div><span class="pulse"></span><strong>Canlı mod kilitli</strong></div><p>${escapeHtml(error.message)}</p><button type="button">Test ölçütleri</button>`}});
testButton.addEventListener("click",()=>{liveButton.classList.remove("live-active");testButton.classList.add("active")});
$("#account-button").addEventListener("click",()=>$("#account-dialog").showModal());
$("#trade-list").innerHTML='<div class="empty-state"><strong>Henüz paper işlem yok</strong><small>Motor yalnızca nitelikli fırsatları test kayıtlarına ekleyecek.</small></div>';
refresh();setInterval(()=>state.user&&refresh(),30000);
