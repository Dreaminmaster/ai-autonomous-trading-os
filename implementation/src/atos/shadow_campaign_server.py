"""Localhost-only Web control plane for resumable Shadow Campaigns."""

from __future__ import annotations

import hmac
import json
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from atos.shadow_campaign import ShadowCampaignError, ShadowCampaignManager

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="atos-control-token" content="__CONTROL_TOKEN__">
  <title>ATOS Shadow Campaign</title>
  <style>
    :root{color-scheme:dark;--bg:#07101c;--panel:#0d1928;--panel2:#101f31;--line:#263950;--text:#e8f0f8;--muted:#8da1b8;--cyan:#3fd9d0;--green:#53d695;--amber:#f1b763;--red:#ff6b75}
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 75% 0,#13253b 0,transparent 32%),var(--bg);color:var(--text);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    main{max-width:1280px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}.eyebrow{color:var(--cyan);font-weight:700;letter-spacing:.11em;text-transform:uppercase}.title{font-size:30px;font-weight:750;margin:4px 0}.bound{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.pill{border:1px solid var(--line);background:#0b1725;border-radius:999px;padding:7px 10px;color:var(--muted)}.pill b{color:var(--text);font-family:ui-monospace,SFMono-Regular,monospace;font-weight:550}.resume{margin:22px 0 14px;border:1px solid #245f63;background:#0d292f;border-radius:12px;padding:13px 16px;color:#baf8f3;display:none}.hero{display:grid;grid-template-columns:1.2fr .8fr;gap:14px}.card{background:linear-gradient(145deg,var(--panel),#0a1522);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 12px 40px #0004}.state-row{display:flex;justify-content:space-between;align-items:center;gap:12px}.state{font-size:25px;font-weight:760}.state small{font-size:13px;color:var(--muted);font-weight:500}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:10px;background:var(--muted);box-shadow:0 0 14px currentColor}.running .dot{background:var(--green)}.warning .dot{background:var(--amber)}.stopped .dot{background:var(--cyan)}.danger .dot{background:var(--red)}.safe{margin-top:12px;color:var(--green)}.actions{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:18px}button{border:1px solid var(--line);border-radius:9px;padding:11px 13px;font-weight:700;color:var(--text);background:#14253a;cursor:pointer}button:hover:not(:disabled){border-color:var(--cyan);transform:translateY(-1px)}button.primary{background:#16877f;border-color:#2ec4ba}button.pause{background:#5f4821;border-color:#a97d34}button.freeze{background:#4b2630;border-color:#8d4354}button:disabled{opacity:.35;cursor:not-allowed}.clock{font:700 44px/1.1 ui-monospace,SFMono-Regular,monospace;margin:16px 0 5px}.label,.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:14px 0}.metric{min-height:112px}.metric .value{font:700 25px/1.2 ui-monospace,SFMono-Regular,monospace;margin-top:14px}.metric .sub{color:var(--muted);margin-top:5px}.ok{color:var(--green)}.bad{color:var(--red)}.progress{height:7px;border-radius:10px;background:#1a2a3b;margin-top:12px;overflow:hidden}.progress>i{display:block;height:100%;background:linear-gradient(90deg,#24b9b0,#53d695);width:0}.lower{display:grid;grid-template-columns:1.45fr .75fr;gap:14px;margin-top:14px}h2{font-size:16px;margin:0 0 14px}table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:var(--muted);font-weight:600;padding:9px;border-bottom:1px solid var(--line)}td{padding:10px 9px;border-bottom:1px solid #1c2c3e;font-family:ui-monospace,SFMono-Regular,monospace}.checks{display:grid;gap:8px}.check{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #1c2c3e;padding:8px 0}.check b{font-size:16px}.footer{display:flex;justify-content:space-between;color:var(--muted);font-size:12px;margin-top:16px}.toast{position:fixed;right:20px;bottom:20px;max-width:420px;background:#14263a;border:1px solid var(--line);padding:13px 16px;border-radius:10px;display:none}.toast.error{border-color:var(--red);color:#ffd3d6}
    @media(max-width:900px){main{padding:16px}.top,.hero,.lower{display:block}.bound{justify-content:flex-start;margin-top:12px}.hero>.card,.lower>.card{margin-top:12px}.grid{grid-template-columns:1fr 1fr}}@media(max-width:520px){.grid,.actions{grid-template-columns:1fr}.clock{font-size:34px}}
  </style>
</head>
<body><main>
  <div class="top"><div><div class="eyebrow">Public-only · Simulated · Live forbidden</div><div class="title">ATOS Shadow Campaign</div><div class="muted">可分段累计、断电可恢复的本地 Shadow 验证</div></div><div class="bound" id="binding"></div></div>
  <div class="resume" id="resumeBanner">继续上次 Campaign</div>
  <section class="hero">
    <div class="card"><div class="state-row"><div class="state" id="state"><span class="dot"></span>加载中</div><div class="pill" id="campaignId">—</div></div><div class="safe" id="safe"></div><div class="actions"><button class="primary" id="newBtn">▶ 开始新 Campaign</button><button id="resumeBtn">▶ 继续运行</button><button class="pause" id="pauseBtn">⏸ 暂停</button><button class="freeze" id="freezeBtn">■ 结束并冻结 Campaign</button></div></div>
    <div class="card"><div class="label">本次连续有效运行时间</div><div class="clock" id="continuous">00:00:00</div><div class="muted" id="heartbeat">最近 heartbeat：—</div><div class="muted" id="okx">OKX 公共数据：—</div></div>
  </section>
  <section class="grid" id="metrics"></section>
  <section class="lower"><div class="card"><h2>历史 Segments</h2><div style="overflow:auto"><table><thead><tr><th>#</th><th>状态</th><th>开始</th><th>结束/heartbeat</th><th>有效时间</th><th>Cycles</th><th>Fills</th><th>Failures</th></tr></thead><tbody id="segments"></tbody></table></div></div><div class="card"><h2>最终验证条件</h2><div class="checks" id="checks"></div></div></section>
  <div class="footer"><span>所有控制仅作用于 localhost 公共数据 Shadow</span><span id="updated">—</span></div>
</main><div class="toast" id="toast"></div>
<script>
const token=document.querySelector('meta[name="atos-control-token"]').content;let busy=false,last=null;
const $=id=>document.getElementById(id);const esc=s=>String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function dur(n){n=Math.max(0,Math.floor(Number(n)||0));const d=Math.floor(n/86400),h=Math.floor(n%86400/3600),m=Math.floor(n%3600/60),s=n%60;return(d?d+'天 ':'')+[h,m,s].map(v=>String(v).padStart(2,'0')).join(':')}
function when(s){if(!s)return'—';try{return new Date(s).toLocaleString('zh-CN',{hour12:false})}catch{return s}}
function metric(label,value,sub,pct){return `<div class="card metric"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div>${pct===null?'':`<div class="progress"><i style="width:${Math.min(100,Math.max(0,pct))}%"></i></div>`}</div>`}
function render(x){last=x;const exists=!!x.campaign_id,m=x.metrics||{},t=x.targets||{};$('state').className='state '+(x.state==='RUNNING'?'running':x.state==='PAUSED'||x.state==='FROZEN'?'stopped':x.state==='RECOVERY_REQUIRED'?'danger':'warning');$('state').innerHTML=`<span class="dot"></span>${esc(x.state_label)}`;$('campaignId').textContent=x.campaign_id||'NO CAMPAIGN';$('safe').textContent=x.safe_to_power_off?'✓ 现在可以安全关机':'运行中：请先点击暂停并等待安全确认';$('safe').className=x.safe_to_power_off?'safe':'safe bad';$('resumeBanner').style.display=x.resume_available?'block':'none';$('binding').innerHTML=exists?[`Commit <b>${esc(x.implementation_sha.slice(0,12))}</b>`,`Policy <b>${esc(x.policy_sha256.slice(0,12))}</b>`,`Strategy <b>${esc(x.strategy_version)}</b>`].map(v=>`<span class="pill">${v}</span>`).join(''):'';$('continuous').textContent=dur(m.current_segment_valid_duration_seconds);$('heartbeat').textContent='最近 heartbeat：'+when(m.last_valid_heartbeat);$('okx').innerHTML='OKX 公共数据：<b class="'+(m.okx_connection_status==='CONNECTED'?'ok':'')+'">'+esc(m.okx_connection_status||'—')+'</b>';
const ratio=(v,g)=>g?Number(v)/Number(g)*100:0;$('metrics').innerHTML=exists?[
 metric('累计有效运行时间',dur(m.valid_duration_seconds),`目标 ${dur(t.minimum_duration_seconds)}`,ratio(m.valid_duration_seconds,t.minimum_duration_seconds)),
 metric('Cycles',Number(m.valid_cycles||0).toLocaleString(),`目标 ${Number(t.minimum_cycles||0).toLocaleString()}`,ratio(m.valid_cycles,t.minimum_cycles)),
 metric('模拟成交数',Number(m.simulated_fills||0).toLocaleString(),`目标 ${Number(t.minimum_simulated_fills||0).toLocaleString()}`,ratio(m.simulated_fills,t.minimum_simulated_fills)),
 metric('PnL',`${Number(m.net_pnl_usdt||0).toFixed(4)} USDT`,`费用 ${Number(m.fees_usdt||0).toFixed(4)} USDT`,null),
 metric('最大回撤',`${Number(m.max_drawdown_pct||0).toFixed(4)}%`,`上限 ${t.max_equity_drawdown_pct}%`,null),
 metric('Failure rate',`${(Number(m.failure_rate||0)*100).toFixed(3)}%`,`上限 ${(Number(t.max_failure_rate||0)*100).toFixed(2)}%`,null),
 metric('最近 heartbeat',when(m.last_valid_heartbeat),m.last_valid_heartbeat?'仅完整有效周期':'等待首个完整周期',null),
 metric('OKX 数据连接',esc(m.okx_connection_status||'—'),m.okx_market_age_seconds==null?'尚无行情':`行情年龄 ${Number(m.okx_market_age_seconds).toFixed(1)} 秒`,null)
].join(''):'';
$('segments').innerHTML=(x.segments||[]).map(s=>`<tr><td>${s.sequence}</td><td>${esc(s.state)}</td><td>${when(s.started_at)}</td><td>${when(s.ended_at||s.last_valid_heartbeat)}</td><td>${dur(s.valid_duration_seconds)}</td><td>${s.valid_cycles||0}</td><td>${s.simulated_fills||0}</td><td>${s.failures||0}</td></tr>`).join('')||'<tr><td colspan="8" class="muted">尚无 Segment</td></tr>';$('checks').innerHTML=(x.validation_conditions||[]).map(c=>`<div class="check"><span>${esc(c.name)}</span><b class="${c.passed?'ok':'bad'}">${c.passed?'✓':'✕'}</b></div>`).join('')||'<div class="muted">创建 Campaign 后显示</div>';
$('newBtn').disabled=busy||x.state==='RUNNING'||x.state==='STARTING'||x.state==='PAUSING';$('resumeBtn').disabled=busy||!x.resume_available;$('pauseBtn').disabled=busy||!['RUNNING','STARTING'].includes(x.state);$('freezeBtn').disabled=busy||!exists||x.state==='FROZEN'||x.state==='RECOVERY_REQUIRED';$('updated').textContent='页面刷新：'+new Date().toLocaleTimeString('zh-CN',{hour12:false});}
function toast(msg,error=false){const e=$('toast');e.textContent=msg;e.className='toast'+(error?' error':'');e.style.display='block';setTimeout(()=>e.style.display='none',6000)}
async function getStatus(){try{const r=await fetch('/api/status',{cache:'no-store'}),x=await r.json();if(!r.ok)throw Error(x.error||r.statusText);render(x)}catch(e){toast(e.message,true)}}
async function act(name){if(busy)return;if(name==='new'&&last?.campaign_id&&!confirm('开始新 Campaign 会保留旧数据，但切换当前 Campaign。继续吗？'))return;if(name==='freeze'&&!confirm('冻结后该 Campaign 不能继续。确定结束吗？'))return;busy=true;render(last||{state:'NONE'});try{const r=await fetch('/api/'+name,{method:'POST',headers:{'Content-Type':'application/json','X-ATOS-Control-Token':token},body:'{}'}),x=await r.json();if(!r.ok)throw Error(x.error||r.statusText);render(x);toast(x.message||'操作完成')}catch(e){toast(e.message,true)}finally{busy=false;await getStatus()}}
$('newBtn').onclick=()=>act('new');$('resumeBtn').onclick=()=>act('resume');$('pauseBtn').onclick=()=>act('pause');$('freezeBtn').onclick=()=>act('freeze');getStatus();setInterval(getStatus,2000);
</script></body></html>"""


class CampaignHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], manager: ShadowCampaignManager):
        super().__init__(address, CampaignRequestHandler)
        self.manager = manager
        self.control_token = secrets.token_urlsafe(32)


class CampaignRequestHandler(BaseHTTPRequestHandler):
    server: CampaignHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        parsed = urlsplit(origin)
        host, port = self.server.server_address
        expected_port = int(port)
        return (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost"}
            and (parsed.port or 80) == expected_port
            and host == "127.0.0.1"
        )

    def _authorized(self) -> bool:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        token = self.headers.get("X-ATOS-Control-Token", "")
        return (
            content_type == "application/json"
            and self._same_origin()
            and hmac.compare_digest(token, self.server.control_token)
        )

    def do_GET(self) -> None:
        if self.path == "/":
            raw = HTML.replace("__CONTROL_TOKEN__", self.server.control_token).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        elif self.path == "/api/status":
            try:
                self._json(HTTPStatus.OK, self.server.manager.status())
            except ShadowCampaignError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc), "live": "FORBIDDEN"})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(HTTPStatus.FORBIDDEN, {"error": "local control authorization failed"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > 4096:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "request body is invalid"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (UnicodeError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "request body is invalid JSON"})
            return
        if not isinstance(body, dict) or body:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "request body must be an empty object"})
            return
        actions = {
            "/api/new": lambda: self.server.manager.create(start=True),
            "/api/resume": self.server.manager.resume,
            "/api/pause": self.server.manager.pause,
            "/api/freeze": self.server.manager.freeze,
        }
        action = actions.get(self.path)
        if action is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            self._json(HTTPStatus.OK, action())
        except ShadowCampaignError as exc:
            self._json(HTTPStatus.CONFLICT, {"error": str(exc), "trade_action": "HOLD", "live": "FORBIDDEN"})
        except Exception:  # noqa: BLE001 - Web boundary does not leak internals
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Campaign operation failed closed", "trade_action": "HOLD", "live": "FORBIDDEN"})


def run_campaign_server(
    manager: ShadowCampaignManager,
    *,
    port: int = 28788,
    open_browser: bool = True,
) -> None:
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("port must be between 1024 and 65535")
    server = CampaignHTTPServer(("127.0.0.1", port), manager)
    url = f"http://127.0.0.1:{server.server_port}/"
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    print(json.dumps({"status": "SERVING", "url": url, "live": "FORBIDDEN"}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
