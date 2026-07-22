#!/usr/bin/env python3
import sys
import os

# Asegurarse que PORT está definido
os.environ.setdefault('PORT', '8000')

# Ejecutar el webhook
exec(open('src/webhook_simple.py').read())
