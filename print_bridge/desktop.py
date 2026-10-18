"""Customer-facing Windows connector and per-user installer."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import webbrowser

from print_bridge.client import APIClient, Bridge, Config, instance_lock, send_print
from print_bridge.renderer import render_escpos
from print_bridge.desktop_core import data_dir, protect, save_settings, load_settings, connection_file, make_config, printers, test_payload


def install():
    import winreg
    if not getattr(sys, 'frozen', False):
        raise ValueError('Use o instalador .exe distribuído para instalar no Windows.')
    target = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'PracaPDVConnector' / 'ConectorPracaPDV.exe'
    target.parent.mkdir(parents=True, exist_ok=True)
    if Path(sys.executable).resolve() != target.resolve():
        shutil.copy2(sys.executable, target)
    command = f'"{target}" "%1"'
    for key, value in [('Software\\Classes\\.pdvconnect', 'PracaPDV.Connection'),
                       ('Software\\Classes\\PracaPDV.Connection', 'Conectar impressora ao Praça PDV'),
                       ('Software\\Classes\\PracaPDV.Connection\\shell\\open\\command', command)]:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, '', 0, winreg.REG_SZ, value)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as handle:
        winreg.SetValueEx(handle, 'PracaPDVConnector', 0, winreg.REG_SZ, f'"{target}" --background')
    shortcut = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Conector Praça PDV.lnk'
    # Paths passed as arguments, never interpolated into PowerShell code.
    script = data_dir() / 'shortcut.ps1'
    script.write_text("param($Target,$Link)\n$s=(New-Object -ComObject WScript.Shell).CreateShortcut($Link)\n$s.TargetPath=$Target\n$s.Save()\n", encoding='utf-8')
    subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), str(target), str(shortcut)],
        check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return target


class Application:
    def __init__(self, root, directory):
        self.root, self.directory = root, directory
        self.path = directory / 'settings.bin'
        self.settings = load_settings(self.path) if self.path.exists() else None
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.status_text = ('Conectando ao SaaS...' if self.settings and self.settings.get('enabled') else
                            'Conectado, mas pausado. Faça o teste para ativar.' if self.settings else 'Ainda não conectado.')
        self.tested = False
        self.print_error = False
        root.title('Conector Praça PDV')
        root.geometry('660x680')
        root.minsize(620, 620)
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Sua impressora, pronta para vender', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Configure uma vez. O conector cuida dos próximos tickets.', wraplength=590).pack(anchor='w', pady=(4,16))
        self.status = tk.StringVar(value=self.status_text)
        ttk.Label(frame, textvariable=self.status, wraplength=590).pack(anchor='w', pady=8)
        ttk.Button(frame, text='1. Instalar e iniciar com o Windows', command=self.install_clicked).pack(fill='x', pady=4)
        row = ttk.Frame(frame); row.pack(fill='x', pady=6)
        self.url = tk.StringVar(value=self.settings['config']['server_url'] if self.settings else 'http://127.0.0.1:8000')
        ttk.Entry(row, textvariable=self.url).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Abrir meu SaaS', command=self.open_saas).pack(side='right')
        ttk.Label(frame, text='No SaaS: Configurações de impressão → Conectar minha impressora.', wraplength=590).pack(anchor='w')
        ttk.Button(frame, text='2. Abrir arquivo de conexão baixado', command=self.choose_link).pack(fill='x', pady=8)
        self.company = tk.StringVar(value=self.settings.get('company','') if self.settings else '')
        ttk.Label(frame, textvariable=self.company, font=('Segoe UI',11,'bold')).pack(anchor='w', pady=4)
        self.transport = tk.StringVar(value='USB / impressora do Windows')
        ttk.Combobox(frame,textvariable=self.transport,values=['USB / impressora do Windows','Rede (IP da impressora)'],state='readonly').pack(fill='x',pady=4)
        self.printer = tk.StringVar(value='POS-80')
        self.printer_box = ttk.Combobox(frame,textvariable=self.printer,state='readonly')
        self.printer_box.pack(fill='x',pady=4)
        ttk.Button(frame,text='Atualizar impressoras',command=self.refresh_printers).pack(anchor='w')
        net = ttk.Frame(frame); net.pack(fill='x',pady=4)
        ttk.Label(net,text='IP (somente rede)').pack(side='left')
        self.host=tk.StringVar(); ttk.Entry(net,textvariable=self.host,width=23).pack(side='left',padx=6)
        ttk.Label(net,text='Porta').pack(side='left')
        self.port=tk.StringVar(value='9100');ttk.Entry(net,textvariable=self.port,width=7).pack(side='left')
        self.cut=tk.BooleanVar(value=True)
        ttk.Checkbutton(frame,text='Cortar papel automaticamente (corte parcial)',variable=self.cut,command=self.invalidate_test).pack(anchor='w',pady=6)
        self.columns=tk.StringVar(value='48')
        self.encoding=tk.StringVar(value='cp860');self.codepage=tk.StringVar(value='3')
        advanced=ttk.Frame(frame)
        def toggle_advanced():
            if advanced.winfo_manager(): advanced.pack_forget()
            else: advanced.pack(fill='x',before=self.test_button)
        ttk.Button(frame,text='Ajustes para outros modelos de impressora',command=toggle_advanced).pack(anchor='w',pady=4)
        for label,var,width in [('Colunas',self.columns,4),('Charset',self.encoding,9),('Tabela',self.codepage,4)]:
            ttk.Label(advanced,text=label).pack(side='left',padx=(0,4));ttk.Entry(advanced,textvariable=var,width=width).pack(side='left',padx=(0,10))
        self.test_button=ttk.Button(frame,text='3. Imprimir teste (sem venda)',command=self.test_print)
        self.test_button.pack(fill='x',pady=6)
        ttk.Button(frame,text='4. Ativar impressão ao confirmar venda e pagamento',command=self.activate).pack(fill='x',pady=6)
        footer=ttk.Frame(frame);footer.pack(fill='x',pady=8)
        ttk.Button(footer,text='Pausar neste computador',command=self.pause).pack(side='left')
        ttk.Button(footer,text='Encerrar conector',command=self.quit).pack(side='right')
        if self.settings:
            c=self.settings['config'];self.printer.set(c['printer_name']);self.host.set(c['host']);self.port.set(str(c['port'] or 9100))
            self.transport.set('Rede (IP da impressora)' if c['transport']=='tcp' else 'USB / impressora do Windows')
            self.cut.set(self.settings.get('cut',True));self.columns.set(str(self.settings.get('columns',48)))
            self.encoding.set(c['encoding']);self.codepage.set(str(c['codepage']))
        for variable in (self.printer,self.transport,self.host,self.port,self.columns,self.encoding,self.codepage):
            variable.trace_add('write',lambda *args:self.invalidate_test())
        root.protocol('WM_DELETE_WINDOW',self.hide)
        threading.Thread(target=self.worker,daemon=True).start()
        root.after(500,self.tick)
        root.after(100,self.refresh_printers)

    def invalidate_test(self): self.tested=False

    def install_clicked(self):
        try:
            install()
            messagebox.showinfo('Instalado','Conector instalado para este usuário. Ele iniciará ao entrar no Windows. Abra-o pelo menu Iniciar.')
        except Exception as exc: messagebox.showerror('Instalação',str(exc))

    def open_saas(self):
        try:
            make_config(self.url.get().strip(),'setup',self.directory)
            webbrowser.open(self.url.get().strip().rstrip('/')+'/printing/settings/')
        except Exception: messagebox.showerror('Endereço','Informe HTTPS para o Render ou http://127.0.0.1:8000 para o SaaS local.')

    def refresh_printers(self):
        try: self.printer_box['values']=printers()
        except Exception as exc: self.status_text=str(exc)

    def choose_link(self):
        path=filedialog.askopenfilename(filetypes=[('Vínculo Praça PDV','*.pdvconnect')])
        if path: self.connect(path)

    def connect(self,path):
        if self.settings:
            messagebox.showinfo('Já conectado','Este computador já está vinculado. Use a configuração existente; para mudar de empresa, peça ao suporte uma desconexão segura.')
            return
        try:
            link=connection_file(path)
            if not messagebox.askyesno('Conectar empresa',f"Conectar este computador a {link['company']}?\n\nServidor: {link['server_url']}\n\nConfira se é o endereço do seu SaaS."): return
            config=make_config(link['server_url'],'setup',self.directory)
            result=APIClient(config,'').post('connector/exchange/',{'link':link['link']})
            config=make_config(link['server_url'],result['printer_identifier'],self.directory)
            self.settings={'config':config.__dict__,'token':result['token'],'company':result['company'],'enabled':False}
            save_settings(self.path,self.settings)
            self.company.set(result['company']);self.url.set(link['server_url'])
            self.status_text='Empresa conectada. Escolha a impressora e teste o papel.'
        except Exception:
            messagebox.showerror('Conexão','Não foi possível conectar. Confira a internet/endereço e baixe um novo vínculo no SaaS. O arquivo vale por 10 minutos.')

    def selected_config(self):
        if not self.settings: raise ValueError('Conecte a empresa primeiro.')
        return make_config(self.settings['config']['server_url'],self.settings['config']['printer_identifier'],self.directory,
            transport='tcp' if self.transport.get().startswith('Rede') else 'windows_raw',printer_name=self.printer.get(),
            host=self.host.get().strip(),port=int(self.port.get()),encoding=self.encoding.get().strip(),codepage=int(self.codepage.get()))

    def test_print(self):
        try:
            config=self.selected_config();columns=int(self.columns.get())
            if not 32<=columns<=64: raise ValueError('Use entre 32 e 64 colunas.')
            with self.lock:
                send_print(config,render_escpos(test_payload(),columns=columns,encoding=config.encoding,codepage=config.codepage,auto_cut=self.cut.get(),feed_lines=5,cut_mode='partial'))
            self.tested=messagebox.askyesno('Confira o papel','O ticket saiu completo, com acentos corretos e o corte esperado?\n\nSe não saiu, confira a fila do Windows antes de tentar novamente.')
        except Exception as exc: messagebox.showerror('Teste não concluído',f'Confira impressora, papel e configuração. ({type(exc).__name__})')

    def activate(self):
        if not self.tested:
            messagebox.showinfo('Teste primeiro','Imprima e confirme o teste antes de ativar.');return
        if not messagebox.askyesno('Impressão automática','Usar esta impressora como padrão da empresa e imprimir as próximas vendas confirmadas?'): return
        try:
            with self.lock:
                config=self.selected_config()
                if Bridge(config,APIClient(config,self.settings['token'])).journal.read():
                    raise ValueError('Há uma confirmação pendente. Aguarde antes de mudar a impressora.')
                APIClient(config,self.settings['token']).post('connector/configure/',{'name':self.printer.get() or 'Impressora de rede','columns':int(self.columns.get()),'cut':self.cut.get(),'automatic':True})
                self.settings.update(config=config.__dict__,enabled=True,cut=self.cut.get(),columns=int(self.columns.get()))
                save_settings(self.path,self.settings)
                self.print_error=False
            self.status_text='Ativado. Aguardando vendas confirmadas.'
        except Exception: messagebox.showerror('Não ativado','Confira a conexão com o SaaS e aguarde trabalhos pendentes antes de alterar a impressora.')

    def pause(self):
        with self.lock:
            if self.settings:
                self.settings['enabled']=False;save_settings(self.path,self.settings)
        self.status_text='Pausado neste computador. Tickets novos permanecem na fila do SaaS.'

    def worker(self):
        while not self.stopping.wait(2):
            with self.lock:
                if not self.settings or not self.settings.get('enabled'): continue
                try:
                    config=Config(**self.settings['config'])
                    def sender(cfg,data):
                        try: return send_print(cfg,data)
                        except Exception:
                            self.print_error=True
                            raise
                    Bridge(config,APIClient(config,self.settings['token']),sender=sender).step()
                    self.status_text=('Falha de impressão: confira papel e a fila no SaaS antes de reimprimir.' if self.print_error else 'Conectado. Aguardando vendas confirmadas.')
                except Exception:
                    self.status_text='Sem conexão ou credencial revogada. Vou tentar novamente; confira se o SaaS está aberto.'

    def tick(self):
        self.status.set(self.status_text)
        inbox=self.directory/'open.json'
        if inbox.exists():
            try:
                request=json.loads(inbox.read_text(encoding='utf-8'));inbox.unlink()
                self.root.deiconify();self.root.lift()
                if request.get('file'): self.connect(request['file'])
            except (OSError,ValueError): pass
        self.root.after(750,self.tick)

    def hide(self):
        if self.settings and self.settings.get('enabled'):
            messagebox.showinfo('Continua funcionando','O conector continuará imprimindo em segundo plano. Para abrir, use o menu Iniciar.')
            self.root.withdraw()
        else: self.quit()

    def quit(self):
        self.stopping.set();self.root.destroy()


def main():
    directory=data_dir();directory.mkdir(parents=True,exist_ok=True)
    file=next((str(Path(arg).resolve()) for arg in sys.argv[1:] if arg.lower().endswith('.pdvconnect')),None)
    lock=instance_lock(directory)
    try: lock.__enter__()
    except RuntimeError:
        (directory/'open.json').write_text(json.dumps({'file':file}),encoding='utf-8');return
    try:
        root=tk.Tk();ttk.Style().theme_use('vista')
        try:
            app=Application(root,directory)
        except Exception:
            messagebox.showerror('Configuração indisponível','Não foi possível abrir a configuração protegida deste usuário. Entre com o mesmo usuário Windows da instalação e procure o suporte. Nenhum registro foi apagado.')
            root.destroy();return
        if '--background' in sys.argv and app.settings and app.settings.get('enabled'): root.withdraw()
        if file: root.after(300,lambda:app.connect(file))
        root.mainloop()
    finally: lock.__exit__(None,None,None)


if __name__=='__main__': main()
