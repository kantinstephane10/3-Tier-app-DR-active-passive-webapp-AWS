'use strict';
const $=id=>document.getElementById(id);
const money=value=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value/100);
const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let products=[],category='All',csrf='',writable=false,busy=false,toastTimer;
let cart={};
try { const saved=JSON.parse(localStorage.getItem('ko-cart')||'{}'); for(const [key,value] of Object.entries(saved)) if(/^[a-z0-9-]{1,64}$/.test(key)&&Number.isInteger(value)&&value>0&&value<=10) cart[key]=value; } catch { /* Start with an empty cart. */ }
async function api(path,options={}) {
  const response=await fetch(path,{credentials:'same-origin',...options});
  const result=await response.json();
  if(!response.ok) throw new Error(result.error||'request_failed');
  return result;
}
function toast(message){ $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,4500); }
function art(id) {
  const shapes={
    'cloud-notebook':'<rect x="39" y="17" width="100" height="141" rx="7" fill="#385c40"/><path d="M49 17v141m77-141v141" stroke="#203f2b" stroke-width="4"/><text x="58" y="72" fill="#e5eccf" font-size="31" font-weight="800">K.</text><path d="M59 115h33m-33 7h23" stroke="#d4e0bd" stroke-width="2"/>',
    'desk-mat':'<rect x="12" y="35" width="155" height="106" rx="12" fill="#6b8772"/><rect x="17" y="40" width="145" height="96" rx="8" fill="none" stroke="#a4b7a0" stroke-dasharray="3 3"/><text x="30" y="72" fill="#dce4d7" font-size="22" font-weight="800">K.</text><path d="M100 92h37m-18-19v37" stroke="#92a891"/>',
    'travel-mug':'<path d="M120 60h15q30 0 30 27t-32 25h-13" fill="none" stroke="#c39b74" stroke-width="13"/><path d="M47 40h79v81q0 31-39 31t-40-31z" fill="#d6b08a"/><ellipse cx="87" cy="40" rx="40" ry="10" fill="#bc966c"/><ellipse cx="87" cy="40" rx="32" ry="5" fill="#554335"/><text x="69" y="105" fill="#495a40" font-size="31" font-weight="800">K.</text>',
    'hoodie':'<path d="M61 49l-25 8-26 64 25 11 21-39v65h72V93l21 39 24-11-25-64-24-8q-30-55-63 0" fill="#455c55"/><path d="M61 49q30 24 63 0m-64 0v42m61-42v42" fill="none" stroke="#879d92" stroke-width="3"/><path d="M70 120h44v27H70z" fill="#3b514a"/><text x="80" y="107" fill="#dfe6d9" font-size="23" font-weight="800">K.</text>',
    'tote':'<path d="M49 53h91l7 105H42z" fill="#d9c5a0"/><path d="M66 55V37q0-30 29-30t29 30v18" fill="none" stroke="#b99e72" stroke-width="8"/><text x="68" y="117" fill="#49623c" font-size="40" font-weight="800">K.</text>',
    'sticker-pack':'<rect x="27" y="33" width="68" height="78" rx="9" fill="#e5b887" transform="rotate(-14 50 60)"/><rect x="84" y="51" width="68" height="78" rx="9" fill="#758f75" transform="rotate(10 120 80)"/><circle cx="77" cy="121" r="34" fill="#e8ecd7" stroke="white" stroke-width="3"/><text x="57" y="134" fill="#3c593d" font-size="34" font-weight="800">K.</text><path d="M48 59l17 18-17 18m51-13h30" fill="none" stroke="#f9f8ed" stroke-width="5"/>'
  };
  return `<svg viewBox="0 0 180 180" aria-hidden="true">${shapes[id]||shapes['cloud-notebook']}</svg>`;
}
function renderProducts(){
  const query=$('search').value.toLowerCase();
  const shown=products.filter(p=>(category==='All'||p.category===category)&&`${p.name} ${p.description}`.toLowerCase().includes(query));
  $('product-count').textContent=`${shown.length} essentials`;
  $('products').innerHTML=shown.map(p=>`<article class="product-card"><div class="product-art"><span class="product-badge">${escape(p.category.toUpperCase())}</span>${art(p.id)}</div><div class="product-info"><div class="product-title">${escape(p.name)}<span>${money(p.priceCents)}</span></div><p>${escape(p.description)}</p><button class="add-button" data-add="${escape(p.id)}">Add to bag +</button></div></article>`).join('')||'<div class="empty">No essentials match your search.</div>';
}
function renderCart(){
  localStorage.setItem('ko-cart',JSON.stringify(cart));
  let count=0,total=0;
  const entries=Object.entries(cart).map(([id,quantity])=>({p:products.find(p=>p.id===id),quantity})).filter(i=>i.p);
  $('cart-items').innerHTML=entries.map(({p,quantity})=>{count+=quantity;total+=p.priceCents*quantity;return `<div class="cart-row"><div><strong>${escape(p.name)}</strong><div class="quantity"><button data-quantity="${p.id}" data-delta="-1" aria-label="Decrease ${escape(p.name)} quantity">−</button><span>${quantity}</span><button data-quantity="${p.id}" data-delta="1" aria-label="Increase ${escape(p.name)} quantity">+</button><button class="remove" data-remove="${p.id}">Remove</button></div></div><span>${money(p.priceCents*quantity)}</span></div>`;}).join('')||'<div class="empty">Your bag is ready for something good.</div>';
  $('cart-count').textContent=count;$('cart-heading-count').textContent=count;$('cart-total').textContent=money(total);
  $('checkout').disabled=busy||!count||!writable;
  $('checkout').textContent=busy?'Placing your order…':writable?'Place demo order ↗':'Standby — checkout unavailable';
}
let cartOpener;
function openCart(){cartOpener=document.activeElement;$('cart-panel').hidden=false;$('cart-overlay').hidden=false;$('cart-toggle').setAttribute('aria-expanded','true');$('cart-close').focus();}
function closeCart(){$('cart-panel').hidden=true;$('cart-overlay').hidden=true;$('cart-toggle').setAttribute('aria-expanded','false');cartOpener?.focus();}
async function orders(){
  $('shop-view').hidden=true;$('orders-view').hidden=false;$('orders-tab').classList.add('active');$('shop-tab').classList.remove('active');
  try {
    const result=await api('/api/orders');
    $('orders-list').innerHTML=result.orders.map(o=>`<article class="order-card"><div><strong>Order ${escape(o.id.slice(0,8).toUpperCase())}</strong><p>${escape(new Date(o.createdAt).toLocaleString())} · ${escape(o.region)}</p></div><span class="order-status">${escape(o.status)}</span><strong>${money(o.totalCents)}</strong></article>`).join('')||'<div class="empty">No orders yet. Your next essential is waiting in the shop.</div>';
  }catch{$('orders-list').textContent='Orders are unavailable. Please try again.';}
}
$('cart-toggle').addEventListener('click',openCart);$('cart-close').addEventListener('click',closeCart);$('cart-overlay').addEventListener('click',closeCart);
document.addEventListener('keydown',event=>{if($('cart-panel').hidden)return;if(event.key==='Escape')closeCart();if(event.key==='Tab'){const focusable=[...$('cart-panel').querySelectorAll('button:not(:disabled)')];const first=focusable[0],last=focusable.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}});
$('browse-button').addEventListener('click',()=>$('collection').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'}));
$('search').addEventListener('input',renderProducts);
document.querySelector('.filters').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;category=b.dataset.category;document.querySelectorAll('.filters button').forEach(n=>n.classList.toggle('selected',n===b));renderProducts();});
$('products').addEventListener('click',e=>{const b=e.target.closest('[data-add]');if(!b||busy)return;const id=b.dataset.add;if((cart[id]||0)>=10)return toast('Maximum quantity is 10.');cart[id]=(cart[id]||0)+1;renderCart();toast('Added to your bag.');});
$('cart-items').addEventListener('click',e=>{if(busy)return;const b=e.target.closest('button');if(!b)return;if(b.dataset.remove)delete cart[b.dataset.remove];else if(b.dataset.quantity){const id=b.dataset.quantity;cart[id]=Math.min(10,(cart[id]||0)+Number(b.dataset.delta));if(cart[id]<=0)delete cart[id];}renderCart();});
$('orders-tab').addEventListener('click',orders);$('refresh-orders').addEventListener('click',orders);$('shop-tab').addEventListener('click',()=>{$('shop-view').hidden=false;$('orders-view').hidden=true;$('shop-tab').classList.add('active');$('orders-tab').classList.remove('active');});
$('checkout').addEventListener('click',async()=>{
  if(busy||!writable)return;
  const items=Object.entries(cart).filter(([id])=>products.some(p=>p.id===id)).map(([productId,quantity])=>({productId,quantity})).sort((a,b)=>a.productId.localeCompare(b.productId));
  const signature=JSON.stringify(items);let attempt;
  try{attempt=JSON.parse(localStorage.getItem('ko-attempt'));}catch{attempt=null;}
  if(!attempt||attempt.signature!==signature)attempt={signature,key:crypto.randomUUID()};
  localStorage.setItem('ko-attempt',JSON.stringify(attempt));busy=true;renderCart();
  try{
    const result=await api('/api/orders',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,'Idempotency-Key':attempt.key},body:JSON.stringify({items})});
    cart={};localStorage.removeItem('ko-attempt');closeCart();toast(`Order ${result.order.id.slice(0,8).toUpperCase()} received.`);await orders();
  }catch(error){toast(error.message==='standby_read_only'?'This region is in standby. Please try later.':'Checkout could not be confirmed. Retry the same bag safely.');}
  finally{busy=false;renderCart();}
});
async function status(){try{const value=await api('/api/status');writable=value.writable;$('runtime-status').textContent=`${value.region} · ${writable?'Active':'Standby'}`;$('status-dot').className=`status-dot ${writable?'ready':'standby'}`;renderCart();}catch{writable=false;$('runtime-status').textContent='Service unavailable';$('status-dot').className='status-dot';renderCart();}}
async function init(){try{const session=await api('/api/session');csrf=session.csrfToken;products=(await api('/api/products')).products;renderProducts();await status();}catch{$('products').innerHTML='<div class="empty">The collection is temporarily unavailable. Please refresh to reconnect.</div>';await status();}}
init();setInterval(status,20000);
