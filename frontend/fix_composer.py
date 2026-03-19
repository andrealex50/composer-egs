with open('/home/andrealex/composer-egs/main.py', 'r') as f:
    text = f.read()

text = text.replace('allow_origins=["*"]', 'allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"]')
with open('/home/andrealex/composer-egs/main.py', 'w') as f:
    f.write(text)
