# Estilo y componentes visuales compartidos.
import streamlit as st

CSS = """
<style>
:root{--bg:#0b1020;--card:#151b33;--line:#26305a;--txt:#e8ecff;--mut:#8f9ac4;
      --ok:#22c55e;--warn:#f59e0b;--bad:#ef4444;--acc:#38bdf8;}
.stApp{background:var(--bg);color:var(--txt);}
.stApp p,.stApp label,.stApp span,.stApp li{color:inherit;}
.block-container{padding-top:1.2rem;padding-bottom:3rem;max-width:1250px;}
.mz-kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;min-height:96px;}
.mz-kpi .l{color:var(--mut);font-size:.78rem;letter-spacing:.04em;text-transform:uppercase;}
.mz-kpi .v{color:var(--txt);font-size:1.75rem;font-weight:700;line-height:1.25;}
.mz-kpi .s{color:var(--mut);font-size:.8rem;}
.mz-kpi.ok{border-left:5px solid var(--ok)} .mz-kpi.warn{border-left:5px solid var(--warn)}
.mz-kpi.bad{border-left:5px solid var(--bad)} .mz-kpi.info{border-left:5px solid var(--acc)}
.mz-chip{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.78rem;font-weight:600;margin-right:6px;}
.mz-chip.ok{background:#12351f;color:#7ee2a0}.mz-chip.warn{background:#3d2e0a;color:#fbd38d}
.mz-chip.bad{background:#3d1414;color:#fca5a5}.mz-chip.info{background:#0e2f42;color:#7dd3fc}
.mz-h{color:var(--txt);font-weight:700;margin:1.2rem 0 .4rem 0;font-size:1.05rem;}
@media (max-width:640px){
  .mz-kpi{min-height:78px;padding:10px 12px}.mz-kpi .v{font-size:1.3rem}
  .block-container{padding-left:.7rem;padding-right:.7rem}
  [data-testid="stHorizontalBlock"]{flex-wrap:wrap;gap:.6rem;row-gap:.6rem}
  [data-testid="stColumn"]{min-width:calc(50% - .5rem)!important;flex:1 1 calc(50% - .5rem)!important}
}
</style>
"""


def aplicar():
    st.markdown(CSS, unsafe_allow_html=True)


def kpi(col, etiqueta, valor, sub="", tono="info"):
    col.markdown(f"<div class='mz-kpi {tono}'><div class='l'>{etiqueta}</div>"
                 f"<div class='v'>{valor}</div><div class='s'>{sub}</div></div>", unsafe_allow_html=True)


def chip(texto, tono="info"):
    return f"<span class='mz-chip {tono}'>{texto}</span>"


def titulo(texto):
    st.markdown(f"<div class='mz-h'>{texto}</div>", unsafe_allow_html=True)
