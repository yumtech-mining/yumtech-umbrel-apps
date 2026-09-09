const state={csrf:"",user:null,exchange:null,opportunities:[],marketFilter:"all",refreshing:false};
const $=(selector,root=document)=>root.querySelector(selector);
const $$=(selector,root=document)=>[...root.querySelectorAll(selector)];
const escapeHtml=value=>String(value??"").replace(/[&<>'"]/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
const tryMoney=value=>new Intl.NumberFormat("tr-TR",{style:"currency",currency:"TRY",maximumFractionDigits:2}).format(Number(value||0));
const numberText=value=>new Intl.NumberFormat("tr-TR",{maximumFractionDigits:8}).format(Number(value||0));
const percent=value=>`%${new Intl.NumberFormat("tr-TR",{maximumFractionDigits:3}).format(Number(value||0)*100)}`;
const PAGE_META={
  overview:["Genel Bakış","İki borsadaki ortak TRY piyasalarını güvenli biçimde izleyin."],
  markets:["Fırsat Tarayıcı","Ücret ve güvenlik payı düşülmüş piyasa fırsatları."],
  trades:["İşlemler","Paper yürütme geçmişi ve iki bacaklı işlem günlükleri."],
  wallets:["Cüzdanlar","Doğrulanmış hesapların salt-okuma varlık görünümü."],
  bot:["BOT · Hummingbot","Test motoru, API kasası ve TRY emir bütçeleri."],
  accounts:["Hesaplar","Yerel kullanıcı profilleri ve bağlantı özeti."],
  risk:["Risk ve Yeterlilik","Canlı işlem kapıları ve test risk profili."],
  system:["Sistem","Bağlantı sağlığı, gizlilik ve denetim kayıtları."]
};

async function api(path,options={}){
  const headers={...(options.body?{"Content-Type":"application/json"}:{}),...(state.csrf?{"X-CSRF-Token":state.csrf}:{}),...options.headers};
  const response=await fetch(path,{credentials:"same-origin",...options,headers});
  if(!response.ok){let detail=`İstek başarısız (${response.status})`;try{detail=(await response.json()).detail||detail}catch{}throw new Error(detail)}
  if(response.status===204)return null;
  return response.json();
}

function setText(id,value){const node=$(id);if(node)node.textContent=value}
function showToast(message,kind=""){
  const toast=$("#toast");if(!toast)return;
  toast.textContent=message;toast.className=`toast show ${kind}`;
  clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>{toast.className="toast"},3600);
}

function navigate(view,{writeHash=true}={}){
  if(!PAGE_META[view])view="overview";
  $$('[data-view-panel]').forEach(panel=>{
    const active=panel.dataset.viewPanel===view;
    panel.hidden=!active;panel.classList.toggle("active",active);
  });
  $$('[data-view]').forEach(link=>link.classList.toggle("active",link.dataset.view===view));
  const [title,subtitle]=PAGE_META[view];setText("#page-title",title);setText("#page-subtitle",subtitle);
  document.title=`${title} · YUMTECH Arbitrage`;
  if(writeHash&&location.hash!==`#${view}`)history.pushState({view},"",`#${view}`);
  window.scrollTo({top:0,behavior:"smooth"});
}

function renderOpportunityTable(selector,items,compact=false){
  const rows=$(selector);if(!rows)return;
  rows.textContent="";
  if(!items.length){rows.innerHTML=`<tr><td colspan="${compact?5:6}" class="empty-cell">${compact?"Güncel uygun fırsat bekleniyor.":"İlk tam derinlik taraması sürüyor. Bu ekran gerçek emir göndermez."}</td></tr>`;return}
  for(const x of items.slice(0,compact?6:50)){
    const tr=document.createElement("tr");
    const pair=String(x.pair||"—"),executable=Boolean(x.executable);
    const common=`<td><div class="pair"><span class="coin">${escapeHtml(pair.slice(0,2))}</span><b>${escapeHtml(pair)}</b></div></td><td class="direction">${escapeHtml(x.buy_exchange)} <b>→</b> ${escapeHtml(x.sell_exchange)}</td><td class="${executable?"profit":"watch"}">${percent(x.net_profit_pct)}</td>`;
    const tail=`<td class="${Number(x.net_profit_try)>=0?"profit":"loss"}">${tryMoney(x.net_profit_try)}</td><td><span class="status-pill ${executable?"":"observe"}">${executable?"PAPER UYGUN":"İZLE"}</span></td>`;
    tr.innerHTML=compact?`${common}${tail}`:`${common}<td>${tryMoney(Number(x.base_amount)*Number(x.buy_vwap))}</td>${tail}`;
    rows.appendChild(tr);
  }
}

function renderMarketTable(){
  const all=state.opportunities||[];
  const items=state.marketFilter==="executable"?all.filter(x=>x.executable):state.marketFilter==="watch"?all.filter(x=>!x.executable):all;
  renderOpportunityTable("#opportunity-rows",items,false);
  setText("#markets-note",`${items.length} fırsat · ${all.length} toplam tarama sonucu · yalnızca public piyasa verisi`);
}

function renderOpportunities(payload){
  state.opportunities=payload.items||[];
  setText("#pair-count",payload.common_pair_count??"—");
  setText("#ready-count",state.opportunities.filter(x=>x.executable).length);
  renderOpportunityTable("#overview-opportunity-rows",state.opportunities.filter(x=>x.executable),true);
  renderMarketTable();
  const ok=Boolean(payload.last_success_ms),feeds=payload.market_data?.feeds||{};
  const feedState=(name)=>{const feed=feeds[name]||{};if(!feed.connected)return "Kesik";if(feed.age_ms==null)return "Bağlanıyor";return feed.age_ms<10000?`${Math.max(0,feed.age_ms)} ms`:`Eski veri · ${Math.round(feed.age_ms/1000)} sn`};
  const btOk=Boolean(feeds.btcturk?.connected&&feeds.btcturk?.age_ms<10000),bnOk=Boolean(feeds.binance_tr?.connected&&feeds.binance_tr?.age_ms<10000);
  setText("#scanner-health",ok&&btOk&&bnOk?"Gerçek zamanlı":ok?"REST yedekli":"Bekliyor");
  setText("#scanner-age",ok?`Son hesaplama ${new Date(payload.last_success_ms).toLocaleTimeString("tr-TR")} · REST yedek ${payload.market_data?.rest_fallback_count||0}`:"Public veriler bekleniyor");
  setText("#bt-health",feedState("btcturk"));setText("#bn-health",feedState("binance_tr"));setText("#scan-health",ok?"Aktif":"Başlıyor");
  const dots=$$(".health-panel i");dots[0]?.classList.toggle("good",btOk);dots[1]?.classList.toggle("good",bnOk);dots[2]?.classList.toggle("good",ok);
}

function updateBudgetPreview(){
  const bt=Number($("#budget-btcturk")?.value||0),bn=Number($("#budget-binance")?.value||0);
  setText("#budget-preview-value",tryMoney(Math.min(bt||0,bn||0)));
}

function renderAccount(data){
  state.user=data;state.csrf=data.csrf_token||"";
  setText("#current-user",data.username);setText("#profile-name",data.username);setText("#profile-role",data.is_admin?"Cihaz yöneticisi":"Yerel kullanıcı");
  const settings=data.settings||{};
  const active=Boolean(Number(settings.active)||settings.active===true);
  if($("#risk-active"))$("#risk-active").value=String(active);
  if($("#bot-active"))$("#bot-active").value=String(active);
  if($("#risk-max"))$("#risk-max").value=settings.max_trade_try||"1000";
  if($("#risk-daily"))$("#risk-daily").value=settings.daily_loss_limit_try||"250";
  if($("#risk-recovery"))$("#risk-recovery").value=settings.max_recovery_loss_try||"100";
  if($("#budget-btcturk"))$("#budget-btcturk").value=settings.btcturk_budget_try||"1000";
  if($("#budget-binance"))$("#budget-binance").value=settings.binance_tr_budget_try||"1000";
  updateBudgetPreview();
  const keys=Object.fromEntries((data.credentials||[]).map(x=>[x.exchange,x]));
  for(const [exchange,keyId,summaryId] of [["btcturk","#bt-key-state","#account-bt-summary"],["binance_tr","#bn-key-state","#account-bn-summary"]]){
    const item=keys[exchange],status=!item?"Bağlı değil":item.validated_at?`Doğrulandı · ${item.key_hint}`:"Kaydedildi · doğrulama gerekli";
    setText(keyId,status);setText(summaryId,status);
    const form=$(`.credential-form[data-exchange="${exchange}"]`),formStatus=form?.querySelector("[data-credential-status]");
    if(formStatus){formStatus.textContent=status;formStatus.className=`form-status ${item?.validated_at?"ok":""}`}
  }
}

function renderBalances(payload){
  const exchanges=Object.fromEntries((payload.exchanges||[]).map(item=>[item.exchange,item]));const tryValues={};
  for(const [exchange,id,statusId,updatedId] of [["btcturk","#bt-balance","#bt-status","#bt-wallet-updated"],["binance_tr","#bn-balance","#bn-status","#bn-wallet-updated"]]){
    const item=exchanges[exchange]||{},tryRow=(item.balances||[]).find(row=>row.asset==="TRY");tryValues[exchange]=Number(tryRow?.available||0);
    setText(id,tryRow?tryMoney(tryRow.available):"—");
    if(item.state==="ok")setText(statusId,tryRow?`TRY kullanılabilir · ${tryMoney(tryRow.available)}`:"Bakiye alındı · TRY yok");
    else if(item.state==="error")setText(statusId,item.error||"Bakiye alınamadı");
    setText(updatedId,item.updated_at_ms?new Date(item.updated_at_ms).toLocaleTimeString("tr-TR"):"—");
    const assetTarget=$(exchange==="btcturk"?"#bt-assets":"#bn-assets");if(!assetTarget)continue;assetTarget.textContent="";
    const assets=(item.balances||[]).filter(row=>Number(row.total||0)>0).slice(0,12);
    if(!assets.length)assetTarget.innerHTML="<small>Varlık bakiyesi yok</small>";
    else assets.forEach(row=>{const pill=document.createElement("small");pill.textContent=`${row.asset} ${numberText(row.total)}`;assetTarget.appendChild(pill)});
  }
  setText("#available-try",tryMoney(payload.available_try_total||0));
  const total=tryValues.btcturk+tryValues.binance_tr;
  if($("#bt-bar"))$("#bt-bar").style.width=total?`${Math.round(tryValues.btcturk/total*100)}%`:"0%";
  if($("#bn-bar"))$("#bn-bar").style.width=total?`${Math.round(tryValues.binance_tr/total*100)}%`:"0%";
}

function renderSummary(payload){
  const execution=payload.execution||{};setText("#today-pnl",tryMoney(execution.today_realized_profit_try||0));setText("#total-pnl",tryMoney(execution.realized_profit_try||0));setText("#week-pnl",tryMoney(execution.seven_days_realized_profit_try||0));setText("#month-pnl",tryMoney(execution.thirty_days_realized_profit_try||0));setText("#trade-ratio",`${execution.balanced||0} / ${execution.total||0}`);setText("#overview-trade-count",execution.total||0);setText("#overview-profitable-count",execution.profitable||0);
  const q=payload.qualification||{};setText("#qualification-summary",`Gözlem ${q.observation_hours||"0"}/72 saat · fırsat ${q.paper_opportunities||0}/100 · paper işlem ${q.paper_trades||0}/20`);
}

function tradeMarkup(item,full){
  const time=item.created_at?new Date(Number(item.created_at)).toLocaleString("tr-TR"):"—",pnl=item.realized_profit_try==null?"Bekliyor":tryMoney(item.realized_profit_try);
  if(full)return `<div><strong>${escapeHtml(item.pair)}</strong><small>${escapeHtml(time)}</small></div><div><strong>${escapeHtml(item.buy_exchange)} → ${escapeHtml(item.sell_exchange)}</strong><small>${escapeHtml(item.state)} · ${escapeHtml(item.mode)}</small></div><div><strong>${numberText(item.requested_base)} coin</strong><small>İstenen base miktarı</small></div><div class="amount ${Number(item.realized_profit_try||0)<0?"loss":"profit"}"><strong>${escapeHtml(pnl)}</strong><small>Gerçekleşen net</small></div>`;
  return `<div><strong>${escapeHtml(item.pair)}</strong><small>${escapeHtml(time)}</small></div><div class="amount ${Number(item.realized_profit_try||0)<0?"loss":"profit"}"><strong>${escapeHtml(pnl)}</strong><small>${escapeHtml(item.state)}</small></div>`;
}
function renderTrades(payload){
  const items=payload.items||[];const full=$("#trade-list"),compact=$("#overview-trade-list");
  if(full){full.textContent="";if(!items.length)full.innerHTML='<div class="empty-state"><strong>Henüz paper işlem yok</strong><small>Motor yalnızca nitelikli fırsatları test kayıtlarına ekleyecek.</small></div>';else items.slice(0,100).forEach(item=>{const row=document.createElement("div");row.className="trade-row full-trade";row.innerHTML=tradeMarkup(item,true);full.appendChild(row)})}
  if(compact){compact.textContent="";if(!items.length)compact.innerHTML='<div class="empty-state"><strong>Henüz paper işlem yok</strong><small>Yeni kayıtlar burada görünecek.</small></div>';else items.slice(0,5).forEach(item=>{const row=document.createElement("div");row.className="trade-row compact-trade";row.innerHTML=tradeMarkup(item,false);compact.appendChild(row)})}
}

function renderHummingbotStatus(hb){
  const labels={idle:"Hazır · test","test-ready":"Test hazır",stopped:"Durduruldu","emergency-stopped":"ACİL DURDURMA",blocked:"Engellendi","not-installed":"Kurulmadı"};
  const label=labels[hb.state]||hb.state||"Bilinmiyor";setText("#hummingbot-health",label);setText("#bot-runtime-state",label);setText("#bot-strategy",hb.strategy||"idle");setText("#bot-orders",hb.orders_submitted??0);setText("#overview-hb-status",label);setText("#hummingbot-note",hb.reason||"Hummingbot hostu yalnızca test kontrolü için hazırdır; canlı emir kapalıdır.");
  const emergency=hb.state==="emergency-stopped";$$('[data-hb-action]').forEach(button=>{button.disabled=emergency&&button.dataset.hbAction!=="start_test"});
}

function renderAudit(payload){
  const list=$("#audit-list");if(!list)return;list.textContent="";const items=payload.items||[];
  if(!items.length){list.innerHTML="<small>Henüz denetim kaydı yok</small>";return}
  items.slice(0,30).forEach(item=>{const row=document.createElement("div");row.className="audit-row";const when=item.created_at?new Date(Number(item.created_at)*1000).toLocaleString("tr-TR"):"—";row.innerHTML=`<span>${escapeHtml(when)}</span><b>${escapeHtml(item.event||"olay")}</b>`;list.appendChild(row)});
}

async function renderQualification(){
  const result=await api("/api/live/qualification"),list=$("#qualification-list");if(!list)return result;list.textContent="";
  const gates=result.gates||{},passed=Object.values(gates).filter(Boolean).length,total=Object.keys(gates).length||8;$(".score").textContent=`${passed}/${total}`;
  const failures=result.failures||[],messages=failures.length?failures:["Bütün canlı işlem kapıları tamamlandı"];
  messages.slice(0,8).forEach(message=>{const li=document.createElement("li");li.innerHTML=`<span>${failures.length?"!":"✓"}</span><div><strong>${escapeHtml(message)}</strong><small>${failures.length?"Canlı mod kilitli":"Yerel onay gerekli"}</small></div>`;list.appendChild(li)});
  return result;
}

async function refresh(){
  if(state.refreshing)return;state.refreshing=true;
  try{const [me,opportunities,health,summary,history,wallets,audit]=await Promise.all([api("/api/me"),api("/api/opportunities"),api("/api/health"),api("/api/metrics/summary"),api("/api/executions?limit=100"),api("/api/balances"),api("/api/audit?limit=30")]);renderAccount(me);renderOpportunities(opportunities);renderHummingbotStatus(health.hummingbot||{});renderSummary(summary);renderTrades(history);renderBalances(wallets);renderAudit(audit);await renderQualification()}
  catch(error){if(/Oturum|geçersiz/.test(error.message))await openAuth();else{setText("#scanner-age",error.message);showToast(error.message,"error")}}
  finally{state.refreshing=false}
}
async function openAuth(){const setup=await api("/api/bootstrap");setText("#auth-title",setup.needs_owner?"İlk kullanıcıyı oluştur":"Oturum aç");$("#auth-form").dataset.endpoint=setup.needs_owner?"/api/bootstrap":"/api/login";if(!$("#auth-dialog").open)$("#auth-dialog").showModal()}

$("#auth-form").addEventListener("submit",async event=>{event.preventDefault();setText("#auth-error","");try{const result=await api(event.currentTarget.dataset.endpoint,{method:"POST",body:JSON.stringify({username:$("#auth-username").value,password:$("#auth-password").value})});state.csrf=result.csrf_token;event.currentTarget.reset();$("#auth-dialog").close();await refresh()}catch(error){setText("#auth-error",error.message)}});

$$('.credential-form').forEach(form=>form.addEventListener("submit",async event=>{event.preventDefault();const exchange=form.dataset.exchange,key=form.querySelector('[data-field="api_key"]'),secret=form.querySelector('[data-field="api_secret"]'),status=form.querySelector("[data-credential-status]"),button=form.querySelector("button[type=submit]");status.textContent="Kaydediliyor…";status.className="form-status";button.disabled=true;try{await api("/api/credentials",{method:"PUT",body:JSON.stringify({exchange,api_key:key.value,api_secret:secret.value})});await api(`/api/credentials/${exchange}/test`,{method:"POST"});key.value="";secret.value="";status.textContent="Doğrulandı";status.className="form-status ok";showToast(`${exchange==="btcturk"?"BTCTürk":"Binance TR"} bağlantısı doğrulandı`);await refresh()}catch(error){key.value="";secret.value="";status.textContent=`Bağlantı testi geçmedi: ${error.message}`;status.className="form-status error";await refresh()}finally{button.disabled=false}}));

$("#add-user-button")?.addEventListener("click",()=>{$("#user-error").textContent="";$("#user-dialog").showModal()});$("#user-cancel")?.addEventListener("click",()=>$("#user-dialog").close());
$("#user-form")?.addEventListener("submit",async event=>{event.preventDefault();setText("#user-error","");try{await api("/api/users",{method:"POST",body:JSON.stringify({username:$("#new-username").value,password:$("#new-password").value})});event.currentTarget.reset();$("#user-dialog").close();showToast("Yeni kullanıcı oluşturuldu")}catch(error){setText("#user-error",error.message)}});

$$('[data-view]').forEach(link=>link.addEventListener("click",event=>{if(link.tagName==="A")event.preventDefault();navigate(link.dataset.view)}));window.addEventListener("popstate",()=>navigate(location.hash.slice(1)||"overview",{writeHash:false}));window.addEventListener("hashchange",()=>navigate(location.hash.slice(1)||"overview",{writeHash:false}));
$$('[data-market-filter]').forEach(button=>button.addEventListener("click",()=>{state.marketFilter=button.dataset.marketFilter;$$('[data-market-filter]').forEach(x=>x.classList.toggle("active",x===button));renderMarketTable()}));

$$('[data-hb-action]').forEach(button=>button.addEventListener("click",async()=>{button.disabled=true;try{await api("/api/hummingbot/control",{method:"POST",body:JSON.stringify({action:button.dataset.hbAction})});showToast("Hummingbot test komutu gönderildi");await refresh()}catch(error){setText("#hummingbot-note",error.message);button.disabled=false;showToast(error.message,"error")}}));
$("#test-details")?.addEventListener("click",()=>navigate("risk"));$("#account-button")?.addEventListener("click",()=>navigate("accounts"));
$("#bot-settings-form")?.addEventListener("submit",async event=>{event.preventDefault();setText("#bot-error","");setText("#bot-saved","");try{await api("/api/settings/bot",{method:"PUT",body:JSON.stringify({active:$("#bot-active").value==="true",btcturk_budget_try:$("#budget-btcturk").value,binance_tr_budget_try:$("#budget-binance").value})});setText("#bot-saved","Ayarlar kaydedildi · test modu");showToast("BOT bütçeleri kaydedildi");await refresh()}catch(error){setText("#bot-error",error.message)}});
$("#budget-btcturk")?.addEventListener("input",updateBudgetPreview);$("#budget-binance")?.addEventListener("input",updateBudgetPreview);
$("#risk-form")?.addEventListener("submit",async event=>{event.preventDefault();setText("#risk-error","");try{await api("/api/settings/test",{method:"PUT",body:JSON.stringify({active:$("#risk-active").value==="true",max_trade_try:$("#risk-max").value,daily_loss_limit_try:$("#risk-daily").value,max_recovery_loss_try:$("#risk-recovery").value})});showToast("Risk ayarları kaydedildi");await refresh()}catch(error){setText("#risk-error",error.message)}});
$("#refresh-balances")?.addEventListener("click",async()=>{try{renderBalances(await api("/api/balances"));showToast("Bakiyeler yenilendi")}catch(error){showToast(error.message,"error")}});

const liveDialog=$("#live-dialog"),liveInput=$("#live-confirm"),confirmLive=$("#confirm-live"),testButton=$("#test-mode"),liveButton=$("#live-mode"),notice=$("#mode-notice");
liveButton.addEventListener("click",async()=>{const result=await renderQualification();liveInput.value="";liveInput.disabled=!result.eligible;confirmLive.disabled=true;liveDialog.showModal();if(result.eligible)liveInput.focus()});liveInput.addEventListener("input",()=>{confirmLive.disabled=liveInput.value.trim()!=="CANLI İŞLEMİ AÇ"});
liveDialog.addEventListener("close",async()=>{if(liveDialog.returnValue!=="confirm"||confirmLive.disabled)return;try{await api("/api/live/enable",{method:"POST"})}catch(error){notice.innerHTML=`<div class="notice-title"><span class="pulse"></span><strong>Canlı mod kilitli</strong></div><p>${escapeHtml(error.message)}</p><button type="button" id="test-details">Güvenlik kapılarını gör</button>`;$("#test-details")?.addEventListener("click",()=>navigate("risk"))}});
testButton.addEventListener("click",()=>{testButton.classList.add("active");liveButton.classList.remove("live-active");navigate("bot")});

navigate(location.hash.slice(1)||"overview",{writeHash:false});refresh();setInterval(()=>state.user&&refresh(),30000);
