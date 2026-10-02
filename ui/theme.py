"""Fawry look & feel. Mobile-first; tablet >=700px; desktop >=1100px."""
HEAD_JS = """<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet"><script>
(function(){
var set=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;
function send(a,v){var f={};document.querySelectorAll('[data-f]').forEach(function(i){f[i.dataset.f]=i.value});
 var ta=document.querySelector('#fw-act textarea'),go=document.querySelector('#fw-go');if(!ta||!go)return;
 set.call(ta,JSON.stringify({a:a,v:v||'',f:f,n:Date.now(),geo:window.__fwgeo||null}));
 ta.dispatchEvent(new Event('input',{bubbles:true}));setTimeout(function(){go.click()},40)}
document.addEventListener('click',function(e){var t=e.target.closest('[data-act]');if(t){e.preventDefault();send(t.dataset.act,t.dataset.v)}});
document.addEventListener('change',function(e){var t=e.target.closest('[data-chg]');if(t)send(t.dataset.chg,t.value)});
document.addEventListener('keydown',function(e){if(e.key==='Enter'){var t=e.target.closest('[data-enter]');if(t){e.preventDefault();send(t.dataset.enter,'')}}});
if(navigator.geolocation)navigator.geolocation.getCurrentPosition(function(p){window.__fwgeo=[p.coords.latitude,p.coords.longitude]},function(){},{timeout:10000,maximumAge:300000});
})();</script>"""

CSS = """
:root{--y:#FFDA00;--yd:#F2CB00;--yl:#FFF3B8;--k:#1d1d1b;--bg:#F2F2F0;--w:#fff;--m:#77777a;--ln:#ececea;--g:#1E7B4D;--r:#D9483B}
.gradio-container{background:var(--bg)!important;max-width:100%!important;padding:0!important;font-family:Inter,"Segoe UI",system-ui,sans-serif!important}
footer,.built-with,#fw-act,#fw-go{display:none!important}
#fw-bridge{position:absolute;left:-9999px;height:0;overflow:hidden}
.gradio-container,gradio-app{--body-text-color:#1d1d1b;--block-padding:0px;--layout-gap:0px;--size-4:0px;--block-border-width:0px;--body-background-fill:#F2F2F0}
gradio-app .app,.gradio-container .app,.gradio-container .main,.gradio-container .wrap,.gradio-container .contain,.gradio-container .fillable,.gradio-container .column,.gradio-container .block,.gradio-container .html-container{padding:0!important;margin:0!important;gap:0!important;max-width:100%!important;border:0!important;box-shadow:none!important;background:transparent!important}
.gradio-container .prose{font-size:inherit!important;color:inherit!important}
.gradio-container .prose *{margin-block:revert}.fw .prose *,.fw *{margin-block:0}
html,body{background:#F2F2F0!important;margin:0}
#fw-root,#fw-root>div,#fw-root .prose{padding:0!important;margin:0!important;border:0!important;max-width:100%!important;background:transparent!important}
.fw,.fw *{box-sizing:border-box;font-family:Inter,"Segoe UI",system-ui,sans-serif;color:var(--k)}
.fw{min-height:100vh;padding-bottom:84px;max-width:1180px;margin:0 auto;background:var(--bg);position:relative}
.fw svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex:none}
.fw button,.fw [data-act]{cursor:pointer;font:inherit;text-align:inherit;-webkit-tap-highlight-color:transparent;user-select:none}
.fw a,.fw a:hover,.fw a:visited,.fw a:focus{text-decoration:none!important;color:inherit}
.fw a{display:block}.fw a.btn,.fw a.ib,.fw a.pill{display:inline-flex}.fw .nav a{display:flex}.fw .chips a,.fw .seg a{display:block}
.fw h1,.fw h2,.fw h3,.fw h4,.fw p,.fw b,.fw small{margin-block:0;font-family:inherit;line-height:1.3;letter-spacing:0}
.fw h2,.fw h3,.fw h4,.fw h1{border:0;padding:0}
.fw input{font-family:inherit;color:var(--k);box-shadow:none}.fw input::placeholder{color:#a3a3a6}
.fw input:focus,.fw select:focus{outline:2px solid var(--y)!important;outline-offset:0;border-color:var(--yd)!important}
.hd{background:var(--y);padding:14px 16px 16px;position:relative}
.row{display:flex;align-items:center;gap:10px}.sp{justify-content:space-between}
.logo{background:var(--k);color:var(--y)!important;font-weight:800;font-size:13px;padding:4px 10px;border-radius:8px}
.pill{background:#ffe96b;font-size:11px;font-weight:600;padding:5px 10px;border-radius:99px;display:flex;gap:5px;align-items:center}.pill svg{width:12px;height:12px}
.av{width:38px;height:38px;border-radius:50%;background:var(--k);color:var(--y)!important;display:grid;place-items:center;font-weight:700;font-size:14px}
.gr{font-size:11px;color:#5a4f00}.nm{font-weight:700;font-size:15px}
.ib{width:36px;height:36px;border-radius:50%;display:grid;place-items:center;background:#ffe96b}.ib.dk{background:var(--k)}.ib.dk svg{stroke:var(--y)}
.bal{background:var(--k);border-radius:18px;padding:14px 16px;margin-top:14px;display:flex;justify-content:space-between;align-items:center;gap:10px}
.bal *{color:#fff}.bal .l{font-size:11px;color:#aaa}.bal .a{font-size:24px;font-weight:800;margin:2px 0}.bal .s{font-size:11px;color:#bbb}
.bal .r{text-align:right;display:flex;flex-direction:column;gap:8px;align-items:flex-end}
.bal .r a{font-size:11px;color:#ddd;cursor:pointer}.bal .r a.btn{font-size:13px;color:var(--k)!important;padding:8px 18px}.bal .r a:not(.btn){text-decoration:underline!important;text-underline-offset:2px}
.btn{transition:transform .12s,filter .15s;background:var(--y);color:var(--k)!important;font-weight:700;font-size:13px;padding:9px 16px;border-radius:99px;display:inline-flex;align-items:center;justify-content:center;gap:6px}
.btn.k{background:var(--k);color:#fff!important}.btn.k *{color:#fff}.btn.l{background:var(--yl)}.btn.o{background:#fff;border:1px solid var(--ln)}.btn.f{width:100%;padding:13px}
.bd{padding:14px 16px;display:grid;gap:14px}
.srch{background:#fff;border-radius:14px;padding:6px 6px 6px 14px;display:flex;align-items:center;gap:8px;border:1px solid var(--ln)}
.srch input{flex:1;border:0!important;outline:0!important;font-size:13px;background:transparent!important;min-width:0;padding:8px 0;box-shadow:none!important}.srch .btn.k{padding:8px 16px;font-size:12px}
.promo{background:var(--y);border-radius:20px;padding:18px;display:flex;justify-content:space-between;align-items:center;gap:12px}
.promo h2{margin:6px 0 4px;font-size:19px;line-height:1.2}.promo p{margin:0 0 12px;font-size:12px;color:#4a4300}
.promo .tag{background:var(--k);color:var(--y)!important;font-size:10px;font-weight:700;padding:3px 8px;border-radius:99px}
.ycard{width:130px;height:176px;flex:none;border:4px solid var(--k);border-radius:16px;background:#2b2b28;padding:12px;display:flex;flex-direction:column;justify-content:space-between}
.ycard *{color:#fff;font-size:10px;font-weight:700}.ycard .chip{width:26px;height:18px;background:#555;border-radius:5px}
.sec{display:flex;justify-content:space-between;align-items:center}.sec h3{margin:0;font-size:15px}.sec a{font-size:12px;color:var(--m);cursor:pointer}
.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.g2{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.card{display:block;background:#fff;border-radius:16px;border:1px solid var(--ln);padding:14px;cursor:pointer;transition:transform .15s,box-shadow .15s}
.card:hover{transform:translateY(-2px);box-shadow:0 6px 18px #0000000f}.card:active,.btn:active,.nav a:active,.ib:active{transform:scale(.97)}
.fw>div:not(.nav):not(.toast){animation:fi .25s ease}@keyframes fi{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.card.q{display:flex;flex-direction:column;align-items:center;gap:8px;font-size:12px;font-weight:600;padding:14px 4px}
.ic{width:36px;height:36px;border-radius:50%;display:grid;place-items:center;flex:none}.c1{background:#FFF3B8}.c2{background:#dcebfb}.c3{background:#d9f0e4}.c4{background:#e6e3fb}
.ft b{display:block;margin:12px 0 2px;font-size:14px}.ft small{display:block;color:var(--m);font-size:11px;min-height:28px}
.fw .chip2{display:inline-block;background:var(--y);font-size:10px;font-weight:700;padding:3px 8px;border-radius:99px;margin-top:8px}
.card.cb{display:flex;align-items:center;gap:12px}.cb .ic{background:var(--k);border-radius:10px}.cb .ic svg{stroke:var(--y)}.cb small{color:var(--m);font-size:11px}
.list{overflow:hidden;background:#fff;border-radius:16px;border:1px solid var(--ln);padding:4px 14px}
.li{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--ln)}.li:last-child{border:0}
.li small{display:block;color:var(--m);font-size:11px}.li b{font-size:13px}.li .am{margin-left:auto;font-weight:700;font-size:13px;white-space:nowrap}.pos{color:var(--g)!important}
.empty{text-align:center;color:var(--m);font-size:13px;padding:22px 10px}
.seg{display:flex;background:#e4e4e1;border-radius:99px;padding:3px;gap:3px}.seg a{flex:1;text-align:center;padding:8px 6px;border-radius:99px;font-size:12px;font-weight:700;color:var(--m);cursor:pointer}.seg a.on{background:var(--k);color:var(--y)}
.chips{display:flex;gap:8px;overflow-x:auto;padding-bottom:2px;scrollbar-width:none}.chips a{white-space:nowrap;background:#fff;border:1px solid var(--ln);padding:6px 12px;border-radius:99px;font-size:12px;font-weight:600;cursor:pointer}.chips a.on{background:var(--y);border-color:var(--y)}
.og{display:grid;grid-template-columns:1fr;gap:10px}
.of{background:#fff;border:1px solid var(--ln);border-radius:16px;padding:14px;display:flex;flex-direction:column;gap:8px}
.of h4{margin:0;font-size:13px;line-height:1.35}.of .meta{font-size:11px;color:var(--m)}.of .acts{display:flex;gap:8px;margin-top:auto}.of .acts .btn{flex:1;padding:8px}
.bgs{display:flex;gap:6px;flex-wrap:wrap;empty-cells:hide}.bgs:empty{display:none}.badge.x{background:#eee;color:var(--m)}.of.xp{opacity:.72}.badge{align-self:flex-start;background:var(--yl);font-size:10px;font-weight:700;padding:3px 8px;border-radius:99px}
select,.fi{width:100%;border:1px solid var(--ln);background:#fff;border-radius:12px;padding:11px 12px;font-size:14px;outline:0}
select{width:auto}.lb{font-size:12px;font-weight:600;margin:8px 0 5px;display:block}
.nav{position:fixed;left:0;right:0;bottom:0;background:#fff;border-top:1px solid var(--ln);display:flex;justify-content:space-around;padding:8px 6px calc(8px + env(safe-area-inset-bottom));z-index:20}
.nav a{display:flex;flex-direction:column;align-items:center;gap:3px;font-size:10px;font-weight:600;color:var(--m);padding:5px 14px;border-radius:99px;cursor:pointer}.nav a.on{box-shadow:0 2px 8px #ffda0080;background:var(--y);color:var(--k);flex-direction:row;gap:6px;font-size:12px;font-weight:700}
.toast{position:fixed;top:14px;left:50%;transform:translateX(-50%);background:var(--k);color:#fff!important;padding:11px 18px;border-radius:12px;font-size:13px;z-index:50;max-width:92vw;animation:tt 4s forwards}
.toast.err{background:var(--r)}@keyframes tt{0%,88%{opacity:1}100%{opacity:0;visibility:hidden}}
.auth{max-width:420px;margin:0 auto;padding:40px 20px}.auth .logo{font-size:20px;padding:6px 14px;display:inline-block}.auth h1{font-size:24px;margin:18px 0 4px}.auth p{color:var(--m);font-size:13px;margin:0 0 14px}
.hint{font-size:11px;background:var(--yl);padding:8px 10px;border-radius:10px;margin-top:12px;line-height:1.5}
@media(min-width:700px){.hd{padding:18px 28px 20px;border-radius:0 0 28px 28px}.bd{padding:18px 28px;gap:18px}.og{grid-template-columns:repeat(2,1fr)}.g4{gap:14px}.ycard{width:150px}.nav{left:50%;right:auto;transform:translateX(-50%);bottom:14px;border:1px solid var(--ln);border-radius:99px;width:min(560px,92vw);box-shadow:0 8px 30px #0002}.fw{padding-bottom:100px}}
@media(min-width:1100px){.g2.f4{grid-template-columns:repeat(4,1fr)}.og{grid-template-columns:repeat(3,1fr)}.hd{margin:0 0 0;padding:20px 40px 24px}.bd{padding:22px 40px}.cols{display:grid;grid-template-columns:2fr 1fr;gap:18px;align-items:start}}
@media(max-width:380px){.bal .a{font-size:20px}.ycard{width:104px;height:150px}.promo h2{font-size:16px}}
"""