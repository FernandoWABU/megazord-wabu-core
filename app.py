# MEGAZORD War Room v5 — punto de entrada (cada página ejecuta solo su propio código).
import streamlit as st

st.set_page_config(page_title="MEGAZORD War Room", page_icon="⚡", layout="wide", initial_sidebar_state="auto")

from core import auth, estilo  # noqa: E402

estilo.aplicar()

if not auth.modo():
    auth.pantalla_login()
    st.stop()

from paginas import centro_mando, batalla, catalogo, eventos  # noqa: E402

paginas = [
    st.Page(centro_mando.render, title="Centro de Mando", icon="🏠", url_path="centro", default=True),
    st.Page(batalla.render, title="Batalla", icon="⚔️", url_path="batalla"),
]
if auth.es_admin():
    paginas += [
        st.Page(catalogo.render, title="Catálogo", icon="⚡", url_path="catalogo"),
        st.Page(eventos.render, title="Eventos", icon="🎯", url_path="eventos"),
    ]

with st.sidebar:
    st.markdown(f"**Modo:** {'Admin' if auth.es_admin() else 'Ejecutivo (solo lectura)'}")
    if st.button("Salir", width="stretch"):
        auth.cerrar_sesion()
        st.rerun()

st.navigation(paginas).run()
