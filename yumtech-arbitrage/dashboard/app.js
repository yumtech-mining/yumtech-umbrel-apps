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
  const ok=Boolean(payload.last_success_ms);
  $("#scanner-health").textContent=ok?"İyi":"Bekliyor";
  $("#scanner-age").textContent=ok?`Son tam tarama ${new Date(payload.last_success_ms).toLocaleTimeString("tr-TR")}`:"Public veriler bekleniyor";
  $("#bt-health").textContent=$("#bn-health").textContent=ok?"Bağlı":"Bekliyor";
  $("#scan-health").textContent=ok?"Aktif":"Başlıyor";
  document.querySelectorAll(".health-panel i").forEach((dot,index)=>dot.classList.toggle("good",ok&&index<3));
}

function renderAccount(data){
  state.user=data;state.csrf=data.csrf_token;$("#current-user").textContent=data.username;
  $("#add-user-button").hidden=!data.is_admin;
  const keys=Object.fromEntries((data.credentials||[]).map(x=>[x.exchange,x]));
  for(const [exchange,id,statusId] of [["btcturk","#bt-key-state","#bt-status"],["binance_tr","#bn-key-state","#bn-status"]]){
    const item=keys[exchange];const text=!item?"Bağlı değil":item.validated_at?`Doğrulandı · ${item.key_hint}`:"Kaydedildi · doğrulama gerekli";
    $(id).textContent=text;$(statusId).textContent=text;
  }
}

async function renderQualification(){
  const result=await api("/api/live/qualification");const list=$("#qualification-list");list.textContent="";
  const failures=result.failures||[];$(".score").textContent=result.eligible?"7/7":`${Math.max(0,7-failures.length)}/7`;
  const messages=failures.length?failures:["Bütün canlı işlem kapıları tamamlandı"];
  messages.slice(0,5).forEach(message=>{const li=document.createElement("li");li.innerHTML=`<span>${failures.length?"!":"✓"}</span><div><strong>${escapeHtml(message)}</strong><small>${failures.length?"Canlı mod kilitli":"Yerel onay gerekli"}</small></div>`;list.appendChild(li)});
  return result;
}

async function refresh(){
  try{const [me,opportunities]=await Promise.all([api("/api/me"),api("/api/opportunities")]);renderAccount(me);renderOpportunities(opportunities);await renderQualification()}
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
document.querySelectorAll("[data-view]").forEach(link=>link.addEventListener("click",()=>{document.querySelectorAll(".nav-item").forEach(x=>x.classList.toggle("active",x===link))}));

const liveDialog=$("#live-dialog"),liveInput=$("#live-confirm"),confirmLive=$("#confirm-live"),testButton=$("#test-mode"),liveButton=$("#live-mode"),notice=$("#mode-notice");
liveButton.addEventListener("click",async()=>{const result=await renderQualification();liveInput.value="";liveInput.disabled=!result.eligible;confirmLive.disabled=true;liveDialog.showModal();if(result.eligible)liveInput.focus()});
liveInput.addEventListener("input",()=>confirmLive.disabled=liveInput.value.trim()!=="CANLI İŞLEMİ AÇ");
liveDialog.addEventListener("close",async()=>{if(liveDialog.returnValue!=="confirm"||confirmLive.disabled)return;try{await api("/api/live/enable",{method:"POST"})}catch(error){notice.innerHTML=`<div><span class="pulse"></span><strong>Canlı mod kilitli</strong></div><p>${escapeHtml(error.message)}</p><button type="button">Test ölçütleri</button>`}});
testButton.addEventListener("click",()=>{liveButton.classList.remove("live-active");testButton.classList.add("active")});
$("#account-button").addEventListener("click",()=>$("#account-dialog").showModal());
$("#trade-list").innerHTML='<div class="empty-state"><strong>Henüz paper işlem yok</strong><small>Motor yalnızca nitelikli fırsatları test kayıtlarına ekleyecek.</small></div>';
refresh();setInterval(()=>state.user&&refresh(),30000);
