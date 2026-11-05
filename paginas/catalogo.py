import streamlit as st
from core import estilo
from core.db import get_db
from modulos.catalogo_rapido import render_catalogo_rapido

REGLAS = ['1. Gladiador', '2. Ancla Mínimo', '3. Cosecha Máximo', '4. Analista Histórico', '9. Ruleta Rusa']


def render():
    render_catalogo_rapido(get_db(), REGLAS, usuario="admin")
