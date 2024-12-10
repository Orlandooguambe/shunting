from flask import Flask, request, redirect, url_for, render_template, flash, session
import sqlite3
import datetime
import random
import io
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
import pdfkit
import xlsxwriter
from io import BytesIO
from flask import send_file, make_response, request, render_template, redirect, url_for
import plotly.graph_objs as go
import plotly.io as pio
import base64
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Função para conectar ao banco de dados
# Conectar ao banco de dados
def conectar_banco():
    return sqlite3.connect("db/escalas.db")


# Rota de login
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == "admin" and password == "admin":
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            flash('Usuário ou senha incorretos')
    return render_template('login.html')


@app.route('/index', methods=['GET', 'POST'])
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    selected_month = request.form.get('selected_month')

    with conectar_banco() as conn:
        cursor = conn.cursor()

        # Carregar a lista de meses disponíveis
        cursor.execute("""
            SELECT DISTINCT strftime('%Y-%m', data) AS mes 
            FROM viagens 
            ORDER BY mes
        """)
        meses_disponiveis = [row[0] for row in cursor.fetchall()]

        if selected_month:
            cursor.execute("""
                SELECT COUNT(*), SUM(toneladas), 
                       (SELECT COUNT(*) FROM funcionarios WHERE disponibilidade = 1), 
                       (SELECT COUNT(*) FROM caminhoes WHERE disponibilidade = 1), 
                       SUM(toneladas * 6.25)
                FROM viagens 
                WHERE strftime('%Y-%m', data) = ?
            """, (selected_month,))
        else:
            cursor.execute("""
                SELECT COUNT(*), SUM(toneladas), 
                       (SELECT COUNT(*) FROM funcionarios WHERE disponibilidade = 1), 
                       (SELECT COUNT(*) FROM caminhoes WHERE disponibilidade = 1), 
                       SUM(toneladas * 6.25)
                FROM viagens 
                WHERE strftime('%Y', data) = strftime('%Y', 'now')
            """)
        
        num_viagens, total_toneladas, num_funcionarios_ativos, num_caminhoes_disponiveis, receita_total = cursor.fetchone()
        
        # Formatar o total de toneladas e receita total para serem mais legíveis
        total_toneladas_formatado = "{:.2f} M".format(total_toneladas / 1_000_000) if total_toneladas else "0"
        receita_total_formatado = "{:.2f} M".format(receita_total / 1_000_000) if receita_total else "0"

        # Gráfico de Linhas com Legenda e Cores
        categorias = ['Viagens Realizadas', 'Toneladas Transportadas', 'Receita Total']
        valores = [num_viagens, total_toneladas, receita_total]
        cores = ['#1f77b4', '#ff7f0e', '#9467bd']
        grafico_linhas_legenda = go.Figure()
        for i, categoria in enumerate(categorias):
            grafico_linhas_legenda.add_trace(go.Scatter(x=[categoria], y=[valores[i]], mode='lines+markers', name=categoria, line=dict(color=cores[i])))
        linhas_legenda_html = pio.to_html(grafico_linhas_legenda, full_html=False)

        # Gráfico de Barras: Viagens por mês (todo o ano)
        cursor.execute("""
            SELECT strftime('%Y-%m', data) AS mes, COUNT(*) 
            FROM viagens 
            WHERE strftime('%Y', data) = strftime('%Y', 'now')
            GROUP BY mes
        """)
        viagens_por_mes = cursor.fetchall()
        meses = [row[0] for row in viagens_por_mes]
        num_viagens_mes = [row[1] for row in viagens_por_mes]
        grafico_barras = go.Figure(data=[go.Bar(x=meses, y=num_viagens_mes)])
        barras_html = pio.to_html(grafico_barras, full_html=False)

        # Gráfico de Pizza: Distribuição de tipos de carga filtrada pelo mês selecionado
        if selected_month:
            cursor.execute("""
                SELECT tipo_carga, COUNT(*)
                FROM viagens
                WHERE strftime('%Y-%m', data) = ?
                GROUP BY tipo_carga
            """, (selected_month,))
        else:
            cursor.execute("""
                SELECT tipo_carga, COUNT(*)
                FROM viagens
                WHERE strftime('%Y', data) = strftime('%Y', 'now')
                GROUP BY tipo_carga
            """)

        tipos_carga = cursor.fetchall()
        carga_labels = [row[0] for row in tipos_carga]
        carga_values = [row[1] for row in tipos_carga]
        grafico_pizza = go.Figure(data=[go.Pie(labels=carga_labels, values=carga_values)])
        pizza_html = pio.to_html(grafico_pizza, full_html=False)

        # Gráfico de Linha: Tendência de toneladas transportadas ao longo do tempo (últimos 30 dias)
        cursor.execute("""
            SELECT strftime('%Y-%m-%d', data) AS dia, SUM(toneladas) 
            FROM viagens 
            WHERE data >= DATE('now', '-30 days')
            GROUP BY dia
        """)
        toneladas_por_dia = cursor.fetchall()
        dias = [row[0] for row in toneladas_por_dia]
        total_toneladas_dia = [row[1] for row in toneladas_por_dia]
        grafico_linha = go.Figure(data=[go.Scatter(x=dias, y=total_toneladas_dia, mode='lines')])
        linha_html = pio.to_html(grafico_linha, full_html=False)

    return render_template('index.html', 
                           titulo="Dashboard",
                           num_viagens=num_viagens, 
                           total_toneladas=total_toneladas_formatado,  # Usando valor formatado
                           num_funcionarios_ativos=num_funcionarios_ativos,
                           num_caminhoes_disponiveis=num_caminhoes_disponiveis,
                           receita_total=receita_total_formatado,  # Usando valor formatado
                           grafico_linhas_legenda=linhas_legenda_html,
                           grafico_barras=barras_html,
                           grafico_pizza=pizza_html,
                           grafico_linha=linha_html,
                           meses=meses_disponiveis,  # Passa a lista de meses disponíveis
                           selected_month=selected_month)

# Rota de funcionários
@app.route('/funcionarios', methods=['GET', 'POST'])
def funcionarios():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    search_type = request.form.get('search_type')
    search_query = request.form.get('search_query')
    
    with conectar_banco() as conn:
        cursor = conn.cursor()
        if search_type and search_query:
            if search_type == 'nome':
                cursor.execute("SELECT * FROM funcionarios WHERE nome LIKE ?", ('%' + search_query + '%',))
            elif search_type == 'numero':
                cursor.execute("SELECT * FROM funcionarios WHERE numero LIKE ?", ('%' + search_query + '%',))
        else:
            cursor.execute("SELECT * FROM funcionarios")
        funcionarios = cursor.fetchall()
    
    return render_template('funcionarios.html', funcionarios=funcionarios, search_type=search_type, search_query=search_query)

# Rota para adicionar ou editar funcionário
@app.route('/add_funcionario', methods=['GET', 'POST'])
@app.route('/add_funcionario/<int:id>', methods=['GET', 'POST'])
def add_funcionario(id=None):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        nome = request.form['nome']
        apelido = request.form['apelido']  # Adicionei o apelido
        cargo = request.form['cargo']
        numero = request.form['numero']
        morada = request.form['morada']  # Adicionei a morada
        bi = request.form['bi']  # Adicionei o BI
        contato = request.form['contato']  # Adicionei o contato
        disponibilidade = request.form.get('disponibilidade') == 'on'
        
        with conectar_banco() as conn:
            cursor = conn.cursor()
            if id:  # Editar funcionário existente
                cursor.execute("""
                    UPDATE funcionarios 
                    SET nome=?, apelido=?, cargo=?, numero=?, morada=?, bi=?, contato=?, disponibilidade=? 
                    WHERE id=?
                """, (nome, apelido, cargo, numero, morada, bi, contato, disponibilidade, id))
            else:  # Adicionar novo funcionário
                cursor.execute("""
                    INSERT INTO funcionarios (nome, apelido, cargo, numero, morada, bi, contato, disponibilidade) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (nome, apelido, cargo, numero, morada, bi, contato, disponibilidade))
            conn.commit()
        
        flash("Funcionário gravado com sucesso")
        return redirect(url_for('add_funcionario'))
    else:
        funcionario = None
        if id:
            with conectar_banco() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, nome, apelido, cargo, numero, morada, bi, contato, disponibilidade 
                    FROM funcionarios 
                    WHERE id=?
                """, (id,))
                row = cursor.fetchone()
                if row:
                    funcionario = {
                        'id': row[0],
                        'nome': row[1],
                        'apelido': row[2],
                        'cargo': row[3],
                        'numero': row[4],
                        'morada': row[5],
                        'bi': row[6],
                        'contato': row[7],
                        'disponibilidade': row[8]
                    }
        
        return render_template('add_funcionario.html', funcionario=funcionario)

# Rota para excluir funcionário
@app.route('/delete_funcionario/<int:id>', methods=['GET'])
def delete_funcionario(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM funcionarios WHERE id=?", (id,))
        conn.commit()
    flash("Funcionário excluído com sucesso")
    return redirect(url_for('funcionarios'))

# Rota para alterar a disponibilidade do funcionario
@app.route('/toggle_disponibilidade_funcionario/<int:id>', methods=['POST'])
def toggle_disponibilidade_funcionario(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    with conectar_banco() as conn: 
        cursor = conn.cursor()
        cursor.execute("UPDATE funcionarios SET disponibilidade = NOT disponibilidade WHERE id = ?", (id,))
        conn.commit()
    return redirect(url_for('funcionarios'))


# Rota de caminhões
# Exibir todos os caminhões
@app.route('/caminhoes', methods=['GET', 'POST'])
def caminhoes():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    search_query = ''
    search_type = ''
    
    if request.method == 'POST':
        search_query = request.form.get('search_query', '')
        search_type = request.form.get('search_type', '')
    
    with conectar_banco() as conn:
        cursor = conn.cursor()
        if search_query:
            query = f"SELECT * FROM caminhoes WHERE {search_type} LIKE ?"
            cursor.execute(query, ('%' + search_query + '%',))
        else:
            cursor.execute("SELECT * FROM caminhoes")
        caminhoes = cursor.fetchall()
    
    return render_template('caminhoes.html', caminhoes=caminhoes, search_query=search_query, search_type=search_type)

# Adicionar/Editar caminhão
@app.route('/add_caminhao', methods=['GET', 'POST'])
@app.route('/add_caminhao/<int:id>', methods=['GET', 'POST'])
def add_caminhao(id=None):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    caminhao = None
    if id:
        with conectar_banco() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM caminhoes WHERE id=?", (id,))
            caminhao = cursor.fetchone()
    
    if request.method == 'POST':
        flet = request.form['flet']
        matricula = request.form['matricula']
        trailer1 = request.form['trailer1']
        trailer2 = request.form['trailer2']
        disponibilidade = 'disponibilidade' in request.form
        
        with conectar_banco() as conn:
            cursor = conn.cursor()
            if id:
                cursor.execute("UPDATE caminhoes SET flet=?, matricula=?, trailer1=?, trailer2=?, disponibilidade=? WHERE id=?", 
                               (flet, matricula, trailer1, trailer2, disponibilidade, id))
            else:
                cursor.execute("INSERT INTO caminhoes (flet, matricula, trailer1, trailer2, disponibilidade) VALUES (?, ?, ?, ?, ?)", 
                               (flet, matricula, trailer1, trailer2, disponibilidade))
            conn.commit()
        
        flash('Caminhão salvo com sucesso!', 'success')
        return redirect(url_for('add_caminhao'))
    
    return render_template('add_caminhao.html', caminhao=caminhao)

# Alterar disponibilidade de caminhão
@app.route('/toggle_disponibilidade_caminhao/<int:id>', methods=['POST'])
def toggle_disponibilidade_caminhao(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT disponibilidade FROM caminhoes WHERE id=?", (id,))
        disponibilidade = cursor.fetchone()[0]
        nova_disponibilidade = not disponibilidade
        cursor.execute("UPDATE caminhoes SET disponibilidade=? WHERE id=?", (nova_disponibilidade, id))
        conn.commit()
    
    return redirect(url_for('caminhoes'))

# Excluir caminhão
@app.route('/delete_caminhao/<int:id>')
def delete_caminhao(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM caminhoes WHERE id=?", (id,))
        conn.commit()
    
    flash('Caminhão excluído com sucesso!', 'success')
    return redirect(url_for('caminhoes'))

   #escala  
def reset_disponibilidade():
    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE caminhoes SET disponibilidade = 1
        """)
        cursor.execute("""
            UPDATE funcionarios SET disponibilidade = 1
        """)
        conn.commit()

def atualizar_turnos_folgas():
    with conectar_banco() as conn:
        cursor = conn.cursor()
        # Resetar disponibilidade e atualizar turnos e folgas
        cursor.execute("""
            UPDATE funcionarios
            SET
                disponibilidade = CASE
                    WHEN dias_folga >= 2 THEN 1
                    ELSE 0
                END,
                turnos_manha = 0,
                turnos_noite = 0,
                dias_folga = CASE
                    WHEN dias_folga >= 2 THEN 0
                    ELSE dias_folga + 1
                END
        """)
        conn.commit()


# Rota de escala
def gerar_escala():
    data_atual = datetime.date.today()
    portos = ['maputo', 'matola']
    turnos = ['manha', 'noite']

    with conectar_banco() as conn:
        cursor = conn.cursor()

        # Verificar se a escala já foi gerada para a data atual
        cursor.execute("SELECT COUNT(*) FROM escalas WHERE data = ?", (data_atual,))
        if cursor.fetchone()[0] > 0:
            flash('A escala já foi gerada para hoje.')
            return

        reset_disponibilidade()

        funcionarios_escalados = {}

        for porto in portos:
            for turno in turnos:
                # Seleciona caminhões disponíveis aleatoriamente
                cursor.execute("""
                    SELECT id FROM caminhoes
                    WHERE disponibilidade = 1
                    ORDER BY RANDOM()
                    LIMIT 20
                """)
                caminhoes_disponiveis = cursor.fetchall()

                # Seleciona funcionários disponíveis aleatoriamente
                cursor.execute("""
                    SELECT id, turnos_manha, turnos_noite, dias_folga FROM funcionarios
                    WHERE disponibilidade = 1
                    ORDER BY RANDOM()
                    LIMIT 20
                """)
                funcionarios_disponiveis = cursor.fetchall()

                # Verificar se há caminhões e funcionários disponíveis suficientes
                if len(caminhoes_disponiveis) == 0 or len(funcionarios_disponiveis) == 0:
                    flash('Não há caminhões ou funcionários suficientes disponíveis para gerar a escala.')
                    return

                for i, caminhao in enumerate(caminhoes_disponiveis):
                    if i < len(funcionarios_disponiveis):
                        funcionario = funcionarios_disponiveis[i]
                        funcionario_id = funcionario[0]

                        # Atualizar turnos e folgas
                        if turno == 'manha':
                            cursor.execute("""
                                UPDATE funcionarios
                                SET turnos_manha = turnos_manha + 1, dias_folga = 0, disponibilidade = 0
                                WHERE id = ?
                            """, (funcionario_id,))
                        elif turno == 'noite':
                            cursor.execute("""
                                UPDATE funcionarios
                                SET turnos_noite = turnos_noite + 1, dias_folga = 0, disponibilidade = 0
                                WHERE id = ?
                            """, (funcionario_id,))

                        funcionarios_escalados[funcionario_id] = turno
                    else:
                        funcionario_id = None

                    # Inserir escala na tabela
                    cursor.execute("""
                        INSERT INTO escalas (data, turno, porto, caminhao_id, funcionario_id)
                        VALUES (?, ?, ?, ?, ?)
                    """, (data_atual, turno, porto, caminhao[0], funcionario_id))

                    # Marcar caminhões utilizados como indisponíveis
                    cursor.execute("""
                        UPDATE caminhoes SET disponibilidade = 0 WHERE id = ?
                    """, (caminhao[0],))

        conn.commit()
        flash('Escala gerada com sucesso!')

# Rota de escala
# Rota de escala
# Rota para gerar escala manualmente
@app.route('/gerar_escala_manual', methods=['GET', 'POST'])
def gerar_escala_manual():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    gerar_escala()
    return redirect(url_for('exibir_escala'))

@app.route('/escala', methods=['GET', 'POST'])
def exibir_escala():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    search_date = request.form.get('search_date', datetime.date.today().isoformat())
    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT e.data, e.turno, e.porto, c.flet, c.matricula, f.nome, f.id
            FROM escalas e
            JOIN caminhoes c ON e.caminhao_id = c.id
            JOIN funcionarios f ON e.funcionario_id = f.id
            WHERE e.data = ?
        """, (search_date,))
        escalas = cursor.fetchall()

        # Calcular prêmio para cada funcionário
        premios = {}
        for escala in escalas:
            funcionario_id = escala[6]
            cursor.execute("""
                SELECT SUM(toneladas) FROM viagens
                WHERE funcionario_id = ? AND strftime('%Y-%m', data) = strftime('%Y-%m', ?)
            """, (funcionario_id, search_date))
            total_toneladas = cursor.fetchone()[0] or 0
            premio = total_toneladas * 6.25
            premios[funcionario_id] = premio

    return render_template('escala.html', escalas=escalas, premios=premios, search_date=search_date)


# Configuração do agendador
scheduler = BackgroundScheduler()
scheduler.add_job(func=gerar_escala, trigger="interval", days=1)
scheduler.start()

# Excell e PDF
@app.route('/download_excel/<date>', methods=['GET'])
def download_excel(date):
    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT e.data, e.turno, e.porto, c.flet, c.matricula, f.nome
            FROM escalas e
            JOIN caminhoes c ON e.caminhao_id = c.id
            JOIN funcionarios f ON e.funcionario_id = f.id
            WHERE e.data = ?
        """, (date,))
        escalas = cursor.fetchall()

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet()

    headers = ['Data', 'Turno', 'Porto', 'Flet', 'Matrícula', 'Funcionário']
    for col_num, header in enumerate(headers):
        worksheet.write(0, col_num, header)

    for row_num, row_data in enumerate(escalas, 1):
        for col_num, cell_data in enumerate(row_data):
            worksheet.write(row_num, col_num, cell_data)

    workbook.close()
    output.seek(0)

    return send_file(output, download_name=f'escala_{date}.xlsx', as_attachment=True)


@app.route('/download_pdf/<date>', methods=['GET'])
def download_pdf(date):
    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT e.data, e.turno, e.porto, c.flet, c.matricula, f.nome
            FROM escalas e
            JOIN caminhoes c ON e.caminhao_id = c.id
            JOIN funcionarios f ON e.funcionario_id = f.id
            WHERE e.data = ?
        """, (date,))
        escalas = cursor.fetchall()

    rendered = render_template('escala_pdf.html', escalas=escalas, search_date=date)
    pdf = pdfkit.from_string(rendered, False)

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=escala_{date}.pdf'

    return response


# Outros códig
@app.route('/registrar_viagem', methods=['GET', 'POST'])
def registrar_viagem():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    search_date = request.args.get('date', datetime.date.today().isoformat())
    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT e.data, e.turno, e.porto, c.flet, c.matricula, f.nome, f.id
            FROM escalas e
            JOIN caminhoes c ON e.caminhao_id = c.id
            JOIN funcionarios f ON e.funcionario_id = f.id
            WHERE e.data = ?
        """, (search_date,))
        escalas = cursor.fetchall()
    
    premios = {}
    for escala in escalas:
        premios[escala[6]] = calcular_premio(escala[6])
    
    mensagem_sucesso = None
    if request.method == 'POST':
        for escala in escalas:
            funcionario_id = escala[6]
            tipo_carga = request.form.get(f'tipo_carga_{funcionario_id}')
            toneladas = request.form.get(f'toneladas_{funcionario_id}')
            
            if tipo_carga and toneladas:
                with conectar_banco() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO viagens (funcionario_id, data, tipo_carga, toneladas, escala_id, caminhao_id)
                        SELECT ?, ?, ?, ?, e.id, e.caminhao_id
                        FROM escalas e
                        WHERE e.data = ? AND e.funcionario_id = ?
                    """, (funcionario_id, search_date, tipo_carga, toneladas, search_date, funcionario_id))
                    conn.commit()
                
                premios[funcionario_id] = calcular_premio(funcionario_id)
        
        mensagem_sucesso = "Viagens registradas com sucesso!"

    return render_template('registrar_viagem.html', escalas=escalas, search_date=search_date, premios=premios, mensagem_sucesso=mensagem_sucesso)

def calcular_premio(funcionario_id):
    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SUM(toneladas) FROM viagens
            WHERE funcionario_id = ? AND strftime('%Y-%m', data) = strftime('%Y-%m', 'now')
        """, (funcionario_id,))
        total_toneladas = cursor.fetchone()[0] or 0
    premio = total_toneladas * 6.25
    return premio


@app.route('/gerenciar_combustivel', methods=['GET'])
def gerenciar_combustivel():
    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rc.id, f.nome, c.matricula, rc.data, rc.quantidade, rc.porto
            FROM requisicoes_combustivel rc
            JOIN funcionarios f ON rc.funcionario_id = f.id
            JOIN caminhoes c ON rc.caminhao_id = c.id
        """)
        requisicoes = cursor.fetchall()
        # Calcular o total de combustível consumido
        cursor.execute("SELECT SUM(quantidade) FROM requisicoes_combustivel")
        total_combustivel = cursor.fetchone()[0]

    return render_template('gerenciar_combustivel.html', requisicoes=requisicoes, total_combustivel=total_combustivel)
    
@app.route('/adicionar_requisicao_combustivel', methods=['GET', 'POST'])
def adicionar_requisicao_combustivel():
    if request.method == 'POST':
        funcionario_id = request.form['funcionario_id']
        caminhao_id = request.form['caminhao_id']
        data = request.form['data']
        quantidade = request.form['quantidade']
        porto = request.form['porto']

        with conectar_banco() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO requisicoes_combustivel (funcionario_id, caminhao_id, data, quantidade, porto)
                VALUES (?, ?, ?, ?, ?)
            """, (funcionario_id, caminhao_id, data, quantidade, porto))
            conn.commit()

            # Obter o ID da última inserção
            requisicao_id = cursor.lastrowid

        flash('Requisição de combustível registrada com sucesso!')

        # Redirecionar para a página de gerenciamento de combustível
        return redirect(url_for('gerenciar_combustivel'))

    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, nome
            FROM funcionarios
        """)
        funcionarios = cursor.fetchall()

        cursor.execute("""
            SELECT id, matricula
            FROM caminhoes
        """)
        caminhoes = cursor.fetchall()

    return render_template('adicionar_requisicao_combustivel.html', funcionarios=funcionarios, caminhoes=caminhoes)

@app.route('/download_requisicao_combustivel_pdf/<int:id>')
def download_requisicao_combustivel_pdf(id):
    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rc.id, f.nome, c.matricula, rc.data, rc.quantidade, rc.porto
            FROM requisicoes_combustivel rc
            JOIN funcionarios f ON rc.funcionario_id = f.id
            JOIN caminhoes c ON rc.caminhao_id = c.id
            WHERE rc.id = ?
        """, (id,))
        requisicao = cursor.fetchone()

    if requisicao:
        funcionario, caminhao, data, quantidade, porto = requisicao[1], requisicao[2], requisicao[3], requisicao[4], requisicao[5]

        html = render_template('requisicao_combustivel_pdf.html',
                               funcionario=funcionario,
                               caminhao=caminhao,
                               data=data,
                               quantidade=quantidade,
                               porto=porto)

        pdf = pdfkit.from_string(html, False)

        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=requisicao_combustivel_{id}.pdf'
        return response

# Rota de relatório
# Rota para Relatório Geral

@app.route('/relatorio_geral', methods=['GET', 'POST'])
def relatorio_geral():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    mes = request.form.get('mes') or datetime.datetime.now().strftime('%Y-%m')
    
    with conectar_banco() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                e.funcionario_id,
                f.nome,
                COUNT(e.id) as total_escalas,
                GROUP_CONCAT(DISTINCT e.turno) as turnos,
                GROUP_CONCAT(DISTINCT e.porto) as portos,
                IFNULL(SUM(v.toneladas), 0) as total_toneladas,
                IFNULL(SUM(CASE WHEN v.tipo_carga = 'carvao' THEN v.toneladas ELSE 0 END), 0) as total_toneladas_carvao,
                IFNULL(SUM(CASE WHEN v.tipo_carga = 'magnetite' THEN v.toneladas ELSE 0 END), 0) as total_toneladas_magnetite,
                IFNULL(SUM(v.toneladas * 6.25), 0) as total_premio
            FROM escalas e
            JOIN funcionarios f ON e.funcionario_id = f.id
            LEFT JOIN viagens v ON e.id = v.escala_id
            WHERE strftime('%Y-%m', e.data) = ?
            GROUP BY e.funcionario_id, f.nome
        """, (mes,))
        
        relatorio_detalhado = cursor.fetchall()

    return render_template('relatorio_geral.html', 
                           relatorio_detalhado=relatorio_detalhado,
                           mes=mes)

#Rota Relatorio Excel
@app.route('/export_excel', methods=['GET', 'POST'])
def export_excel():
    mes = request.args.get('mes') or datetime.datetime.now().strftime('%Y-%m')
    
    with conectar_banco() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                e.funcionario_id,
                f.nome,
                COUNT(e.id) as total_escalas,
                GROUP_CONCAT(DISTINCT e.turno) as turnos,
                GROUP_CONCAT(DISTINCT e.porto) as portos,
                IFNULL(SUM(v.toneladas), 0) as total_toneladas,
                IFNULL(SUM(CASE WHEN v.tipo_carga = 'carvao' THEN v.toneladas ELSE 0 END), 0) as total_toneladas_carvao,
                IFNULL(SUM(CASE WHEN v.tipo_carga = 'magnetite' THEN v.toneladas ELSE 0 END), 0) as total_toneladas_magnetite,
                IFNULL(SUM(v.toneladas * 6.25), 0) as total_premio
            FROM escalas e
            JOIN funcionarios f ON e.funcionario_id = f.id
            LEFT JOIN viagens v ON e.id = v.escala_id
            WHERE strftime('%Y-%m', e.data) = ?
            GROUP BY e.funcionario_id, f.nome
        """, (mes,))
        
        relatorio_detalhado = cursor.fetchall()
    
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet()

    headers = ['Funcionário', 'Total de Escalas', 'Turnos', 'Portos', 'Total de Toneladas', 'Total de Carvão', 'Total de Magnetite', 'Total de Prêmio']
    for col_num, header in enumerate(headers):
        worksheet.write(0, col_num, header)

    for row_num, row in enumerate(relatorio_detalhado, 1):
        for col_num, data in enumerate(row[1:]):
            worksheet.write(row_num, col_num, data)

    workbook.close()
    output.seek(0)

    return send_file(output, download_name='relatorio_geral.xlsx', as_attachment=True)

#Rota Relatorio pdf
@app.route('/export_pdf', methods=['GET', 'POST'])
def export_pdf():
    mes = request.args.get('mes') or datetime.datetime.now().strftime('%Y-%m')
    
    with conectar_banco() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                e.funcionario_id,
                f.nome,
                COUNT(e.id) as total_escalas,
                GROUP_CONCAT(DISTINCT e.turno) as turnos,
                GROUP_CONCAT(DISTINCT e.porto) as portos,
                IFNULL(SUM(v.toneladas), 0) as total_toneladas,
                IFNULL(SUM(CASE WHEN v.tipo_carga = 'carvao' THEN v.toneladas ELSE 0 END), 0) as total_toneladas_carvao,
                IFNULL(SUM(CASE WHEN v.tipo_carga = 'magnetite' THEN v.toneladas ELSE 0 END), 0) as total_toneladas_magnetite,
                IFNULL(SUM(v.toneladas * 6.25), 0) as total_premio
            FROM escalas e
            JOIN funcionarios f ON e.funcionario_id = f.id
            LEFT JOIN viagens v ON e.id = v.escala_id
            WHERE strftime('%Y-%m', e.data) = ?
            GROUP BY e.funcionario_id, f.nome
        """, (mes,))
        
        relatorio_detalhado = cursor.fetchall()
    
    rendered = render_template('relatorio_pdf.html', relatorio_detalhado=relatorio_detalhado, mes=mes)
    
    pdf = pdfkit.from_string(rendered, False)
    
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=relatorio_geral.pdf'
    
    return response

    #Relatorio_Detalhado
@app.route('/relatorio_detalhado', methods=['GET'])
def relatorio_detalhado():
    mes = request.args.get('mes')
    nome_funcionario = request.args.get('nome_funcionario')

    query_funcionarios = "SELECT id, nome, apelido FROM funcionarios"
    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute(query_funcionarios)
        funcionarios = cursor.fetchall()

    query = """
        SELECT e.data, e.porto, e.turno,
               SUM(v.toneladas) AS total_toneladas,
               SUM(CASE WHEN v.tipo_carga = 'Carvão' THEN v.toneladas ELSE 0 END) AS total_carvao,
               SUM(CASE WHEN v.tipo_carga = 'Magnetite' THEN v.toneladas ELSE 0 END) AS total_magnetite
        FROM escalas e
        JOIN viagens v ON e.id = v.escala_id
        JOIN funcionarios f ON e.funcionario_id = f.id
    """
    params = []

    if mes:
        query += " WHERE strftime('%Y-%m', e.data) = ?"
        params.append(mes)

    if nome_funcionario:
        query += " AND f.nome LIKE ?" if mes else " WHERE f.nome LIKE ?"
        params.append(f'%{nome_funcionario}%')

    query += " GROUP BY e.data, e.porto, e.turno ORDER BY e.data DESC"

    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        relatorio_detalhado = cursor.fetchall()

    relatorio_detalhado = [
        {
            'data': row[0],
            'porto': row[1],
            'turno': row[2],
            'total_toneladas': row[3],
            'total_carvao': row[4],
            'total_magnetite': row[5],
            'premio': row[3] * 6.25  # Prêmio calculado como toneladas totais * 6.25
        }
        for row in relatorio_detalhado
    ]

    total_premio = sum(row['premio'] for row in relatorio_detalhado)

    return render_template(
        'relatorio_detalhado.html',
        relatorio_detalhado=relatorio_detalhado,
        mes=mes,
        nome_funcionario=nome_funcionario,
        funcionarios=funcionarios,
        total_premio=total_premio
    )

@app.route('/export_pdf_detalhado')
def export_pdf_detalhado():
    mes = request.args.get('mes')
    nome_funcionario = request.args.get('nome_funcionario')

    query = """
        SELECT e.data, e.porto, e.turno,
               SUM(v.toneladas) AS total_toneladas,
               SUM(CASE WHEN v.tipo_carga = 'Carvão' THEN v.toneladas ELSE 0 END) AS total_carvao,
               SUM(CASE WHEN v.tipo_carga = 'Magnetite' THEN v.toneladas ELSE 0 END) AS total_magnetite
        FROM escalas e
        JOIN viagens v ON e.id = v.escala_id
        JOIN funcionarios f ON e.funcionario_id = f.id
    """
    params = []

    if mes:
        query += " WHERE strftime('%Y-%m', e.data) = ?"
        params.append(mes)

    if nome_funcionario:
        query += " AND f.nome LIKE ?" if mes else " WHERE f.nome LIKE ?"
        params.append(f'%{nome_funcionario}%')

    query += " GROUP BY e.data, e.porto, e.turno ORDER BY e.data DESC"

    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        relatorio_detalhado = cursor.fetchall()

    relatorio_detalhado = [
        {
            'data': row[0],
            'porto': row[1],
            'turno': row[2],
            'total_toneladas': row[3],
            'total_carvao': row[4],
            'total_magnetite': row[5],
            'premio': row[3] * 6.25  # Prêmio calculado como toneladas totais * 6.25
        }
        for row in relatorio_detalhado
    ]

    total_premio = sum(row['premio'] for row in relatorio_detalhado)

    rendered = render_template(
        'relatorio_detalhado_pdf.html',
        relatorio_detalhado=relatorio_detalhado,
        total_premio=total_premio
    )

    pdf_output = pdfkit.from_string(rendered, False)

    response = make_response(pdf_output)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=relatorio_detalhado.pdf'

    return response




@app.route('/relatorio_combustivel', methods=['GET', 'POST'])
def relatorio_combustivel():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    mes = request.form.get('mes') if request.method == 'POST' else request.args.get('mes')

    with conectar_banco() as conn:
        cursor = conn.cursor()

        query = """
            SELECT f.nome, c.flet, r.data, r.quantidade, r.porto
            FROM requisicoes_combustivel r
            JOIN funcionarios f ON r.funcionario_id = f.id
            JOIN caminhoes c ON r.caminhao_id = c.id
        """
        params = []
        if mes:
            query += " WHERE strftime('%Y-%m', r.data) = ?"
            params.append(mes)
        query += " ORDER BY r.data DESC"

        cursor.execute(query, params)
        relatorio_combustivel = cursor.fetchall()

    return render_template('relatorio_combustivel.html', relatorio_combustivel=relatorio_combustivel, mes=mes)

@app.route('/export_pdf_combustivel')
def export_pdf_combustivel():
    mes = request.args.get('mes')

    with conectar_banco() as conn:
        cursor = conn.cursor()

        query = """
            SELECT f.nome, c.flet, r.data, r.quantidade, r.porto
            FROM requisicoes_combustivel r
            JOIN funcionarios f ON r.funcionario_id = f.id
            JOIN caminhoes c ON r.caminhao_id = c.id
        """
        params = []
        if mes:
            query += " WHERE strftime('%Y-%m', r.data) = ?"
            params.append(mes)
        query += " ORDER BY r.data DESC"

        cursor.execute(query, params)
        relatorio_combustivel = cursor.fetchall()

    rendered = render_template(
        'relatorio_combustivel_pdf.html',
        relatorio_combustivel=relatorio_combustivel,
        mes=mes
    )

    pdf_output = pdfkit.from_string(rendered, False)

    response = make_response(pdf_output)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=relatorio_combustivel_{mes}.pdf'

    return response


#Rota de Definicoes
@app.route('/definicoes')
def definicoes():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('definicoes.html')

@app.route('/perfil')
def perfil():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    return render_template('perfil.html')

@app.route('/adicionar_usuario', methods=['GET', 'POST'])
def adicionar_usuario():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = generate_password_hash(password)  # Use a secure method to hash the password

        with conectar_banco() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO usuarios (username, password) VALUES (?, ?)", (username, hashed_password))
            conn.commit()

        return redirect(url_for('definicoes'))

    return render_template('adicionar_usuario.html')

@app.route('/configurar_perfil', methods=['GET', 'POST'])
def configurar_perfil():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_id = request.form['user_id']
        perfil = request.form['perfil']

        with conectar_banco() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE usuarios SET perfil = ? WHERE id = ?", (perfil, user_id))
            conn.commit()

        return redirect(url_for('definicoes'))

    with conectar_banco() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username FROM usuarios")
        usuarios = cursor.fetchall()

    return render_template('configurar_perfil.html', usuarios=usuarios)


@app.route('/logout')
def logout():
    session['logged_in'] = False
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)

