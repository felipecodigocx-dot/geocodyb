from flask import Flask, request, render_template, jsonify, send_file
from flask_cors import CORS
import pandas as pd
import folium
from folium.plugins import HeatMap
import os
import tempfile
import uuid
from werkzeug.utils import secure_filename
import traceback
import numpy as np
import requests
import json

app = Flask(__name__)
CORS(app)

# Configurações
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB máximo
UPLOAD_FOLDER = 'uploads'
MAPS_FOLDER = 'generated_maps'

# Criar pastas se não existirem
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(MAPS_FOLDER, exist_ok=True)

# Mapeamento dos estados brasileiros
ESTADOS_BRASIL = {
    'acre': 'AC',
    'alagoas': 'AL', 
    'amapá': 'AP',
    'amapa': 'AP',
    'amazonas': 'AM',
    'bahia': 'BA',
    'ceará': 'CE',
    'ceara': 'CE',
    'distrito federal': 'DF',
    'espírito santo': 'ES',
    'espirito santo': 'ES',
    'goiás': 'GO',
    'goias': 'GO',
    'maranhão': 'MA',
    'maranhao': 'MA',
    'mato grosso': 'MT',
    'mato grosso do sul': 'MS',
    'minas gerais': 'MG',
    'pará': 'PA',
    'para': 'PA',
    'paraíba': 'PB',
    'paraiba': 'PB',
    'paraná': 'PR',
    'parana': 'PR',
    'pernambuco': 'PE',
    'piauí': 'PI',
    'piaui': 'PI',
    'rio de janeiro': 'RJ',
    'rio grande do norte': 'RN',
    'rio grande do sul': 'RS',
    'rondônia': 'RO',
    'rondonia': 'RO',
    'roraima': 'RR',
    'santa catarina': 'SC',
    'são paulo': 'SP',
    'sao paulo': 'SP',
    'sergipe': 'SE',
    'tocantins': 'TO'
}

# GeoJSON dos estados brasileiros (simplificado para exemplo)
# Em produção, você pode carregar de um arquivo ou API
GEOJSON_ESTADOS = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"

def allowed_file(filename):
    """Verifica se o arquivo é um Excel válido"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ['xlsx', 'xls']

def obter_geojson_estados():
    """Obtém o GeoJSON dos estados brasileiros"""
    try:
        response = requests.get(GEOJSON_ESTADOS, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            # Fallback: GeoJSON simplificado dos estados
            return criar_geojson_fallback()
    except:
        return criar_geojson_fallback()

def criar_geojson_fallback():
    """Cria um GeoJSON básico dos estados brasileiros para fallback"""
    # Este é um exemplo simplificado - em produção use dados completos
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "São Paulo", "sigla": "SP"},
                "geometry": {"type": "Polygon", "coordinates": [[[-44, -20], [-44, -25], [-48, -25], [-48, -20], [-44, -20]]]}
            },
            {
                "type": "Feature", 
                "properties": {"name": "Rio de Janeiro", "sigla": "RJ"},
                "geometry": {"type": "Polygon", "coordinates": [[[-40, -20], [-40, -24], [-45, -24], [-45, -20], [-40, -20]]]}
            }
            # Adicione mais estados conforme necessário
        ]
    }

def processar_excel(filepath):
    """
    Processa o arquivo Excel e extrai coordenadas, descrições e quantidades
    Formato esperado: colunas 'latitude', 'longitude', 'descricao', 'quantidade' (opcional)
    Para mapas coropléticos: 'estado', 'quantidade'
    """
    try:
        # Tentar ler o arquivo Excel
        df = pd.read_excel(filepath)
        
        # Verificar se é mapa coroplético (tem coluna estado)
        colunas_estado = ['estado', 'states', 'uf', 'sigla']
        tem_coluna_estado = any(col.lower() in [c.lower() for c in df.columns] for col in colunas_estado)
        
        if tem_coluna_estado:
            return processar_excel_estados(df)
        else:
            return processar_excel_coordenadas(df)
        
    except Exception as e:
        raise Exception(f"Erro ao processar Excel: {str(e)}")

def processar_excel_estados(df):
    """Processa Excel para mapa coroplético dos estados"""
    try:
        # Encontrar coluna de estados
        col_estado = None
        colunas_estado = ['estado', 'states', 'uf', 'sigla']
        
        for col_est in colunas_estado:
            for col_exist in df.columns:
                if col_exist.lower() == col_est:
                    col_estado = col_exist
                    break
            if col_estado:
                break
        
        if not col_estado:
            raise ValueError("Coluna de estado não encontrada. Use: 'estado', 'uf' ou 'sigla'")
        
        # Encontrar coluna de quantidade
        col_quantidade = None
        colunas_opcionais = ['quantidade', 'intensidade', 'valor', 'peso', 'populacao', 'population']
        
        for col_opcional in colunas_opcionais:
            for col_exist in df.columns:
                if col_exist.lower() == col_opcional:
                    col_quantidade = col_exist
                    break
            if col_quantidade:
                break
        
        if not col_quantidade:
            raise ValueError("Coluna de quantidade não encontrada para mapa coroplético")
        
        # Padronizar colunas
        df_processado = df.rename(columns={
            col_estado: 'estado',
            col_quantidade: 'quantidade'
        })
        
        # Filtrar apenas colunas necessárias
        df_processado = df_processado[['estado', 'quantidade']]
        
        # Remover linhas com valores nulos
        df_processado = df_processado.dropna()
        
        # Converter quantidade para numérico
        df_processado['quantidade'] = pd.to_numeric(df_processado['quantidade'], errors='coerce')
        df_processado = df_processado.dropna(subset=['quantidade'])
        df_processado = df_processado[df_processado['quantidade'] >= 0]
        
        # Normalizar nomes dos estados
        df_processado['estado_normalizado'] = df_processado['estado'].str.lower().str.strip()
        
        if df_processado.empty:
            raise ValueError("Nenhum dado válido encontrado para mapa coroplético")
        
        dados = df_processado.to_dict('records')
        return dados, True, 'coroplético'
        
    except Exception as e:
        raise Exception(f"Erro ao processar dados de estados: {str(e)}")

def processar_excel_coordenadas(df):
    """Processa Excel para mapas de coordenadas (função original)"""
    try:
        # Verificar colunas obrigatórias
        colunas_obrigatorias = ['latitude', 'longitude', 'descricao']
        colunas_opcionais = ['quantidade', 'intensidade', 'valor', 'peso']
        
        # Mapear colunas (case insensitive)
        mapeamento_colunas = {}
        
        # Mapear colunas obrigatórias
        for col_obrig in colunas_obrigatorias:
            col_encontrada = None
            for col_exist in df.columns:
                if col_exist.lower() == col_obrig:
                    col_encontrada = col_exist
                    break
            
            if not col_encontrada:
                # Tentar variações comuns
                if col_obrig == 'latitude':
                    alternativas = ['lat', 'y', 'latitude']
                elif col_obrig == 'longitude':
                    alternativas = ['lon', 'lng', 'long', 'x', 'longitude']
                elif col_obrig == 'descricao':
                    alternativas = ['descricao', 'descrição', 'description', 'nome', 'name', 'titulo', 'título']
                
                for alt in alternativas:
                    for col_exist in df.columns:
                        if col_exist.lower() == alt:
                            col_encontrada = col_exist
                            break
                    if col_encontrada:
                        break
            
            if not col_encontrada:
                raise ValueError(f"Coluna '{col_obrig}' não encontrada. Colunas disponíveis: {list(df.columns)}")
            
            mapeamento_colunas[col_obrig] = col_encontrada
        
        # Mapear coluna de quantidade (opcional)
        col_quantidade = None
        for col_opcional in colunas_opcionais:
            for col_exist in df.columns:
                if col_exist.lower() == col_opcional:
                    col_quantidade = col_exist
                    break
            if col_quantidade:
                break
        
        # Renomear colunas para padronização
        rename_dict = {
            mapeamento_colunas['latitude']: 'latitude',
            mapeamento_colunas['longitude']: 'longitude',
            mapeamento_colunas['descricao']: 'descricao'
        }
        
        if col_quantidade:
            rename_dict[col_quantidade] = 'quantidade'
            colunas_finais = ['latitude', 'longitude', 'descricao', 'quantidade']
        else:
            colunas_finais = ['latitude', 'longitude', 'descricao']
        
        df_processado = df.rename(columns=rename_dict)
        
        # Filtrar apenas as colunas necessárias
        df_processado = df_processado[colunas_finais]
        
        # Remover linhas com valores nulos nas colunas obrigatórias
        df_processado = df_processado.dropna(subset=['latitude', 'longitude', 'descricao'])
        
        # Validar coordenadas
        df_processado = df_processado[
            (df_processado['latitude'].between(-90, 90)) & 
            (df_processado['longitude'].between(-180, 180))
        ]
        
        # Se existe coluna quantidade, garantir que seja numérica
        if col_quantidade:
            df_processado['quantidade'] = pd.to_numeric(df_processado['quantidade'], errors='coerce')
            # Remover linhas onde quantidade é NaN
            df_processado = df_processado.dropna(subset=['quantidade'])
            # Garantir que quantidade seja positiva
            df_processado = df_processado[df_processado['quantidade'] > 0]
        
        if df_processado.empty:
            raise ValueError("Nenhuma coordenada válida encontrada no arquivo")
        
        # Adicionar informação se tem quantidade
        dados = df_processado.to_dict('records')
        tem_quantidade = col_quantidade is not None
        
        return dados, tem_quantidade, 'coordenadas'
        
    except Exception as e:
        raise Exception(f"Erro ao processar coordenadas: {str(e)}")

def obter_tiles_mapa(tema='claro'):
    """Retorna configuração de tiles baseada no tema"""
    if tema == 'escuro':
        return 'CartoDB dark_matter'
    else:
        return 'OpenStreetMap'

def criar_mapa_tradicional(dados_coordenadas, tema='claro'):
    """Cria mapa tradicional com marcadores"""
    # Calcular centro do mapa
    lats = [ponto['latitude'] for ponto in dados_coordenadas]
    lons = [ponto['longitude'] for ponto in dados_coordenadas]
    
    centro_lat = sum(lats) / len(lats)
    centro_lon = sum(lons) / len(lons)
    
    # Criar mapa
    mapa = folium.Map(
        location=[centro_lat, centro_lon],
        zoom_start=10,
        tiles=obter_tiles_mapa(tema)
    )
    
    # Cores para diferentes pontos
    cores = ['red', 'blue', 'green', 'purple', 'orange', 'darkred', 
            'pink', 'gray', 'black', 'darkblue', 'darkgreen', 'cadetblue']
    
    # Adicionar marcadores
    for i, ponto in enumerate(dados_coordenadas):
        cor = cores[i % len(cores)]
        
        # Criar popup com informações
        popup_html = f"""
        <div style="width: 200px;">
            <h4>{ponto['descricao']}</h4>
            <p><strong>Latitude:</strong> {ponto['latitude']:.6f}</p>
            <p><strong>Longitude:</strong> {ponto['longitude']:.6f}</p>
        """
        
        if 'quantidade' in ponto:
            popup_html += f"<p><strong>Quantidade:</strong> {ponto['quantidade']}</p>"
        
        popup_html += "</div>"
        
        folium.Marker(
            location=[ponto['latitude'], ponto['longitude']],
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=ponto['descricao'],
            icon=folium.Icon(color=cor, icon='info-sign')
        ).add_to(mapa)
    
    return mapa

def criar_mapa_calor(dados_coordenadas, tema='claro'):
    """Cria mapa de calor (heatmap) usando as quantidades"""
    # Calcular centro do mapa
    lats = [ponto['latitude'] for ponto in dados_coordenadas]
    lons = [ponto['longitude'] for ponto in dados_coordenadas]
    
    centro_lat = sum(lats) / len(lats)
    centro_lon = sum(lons) / len(lons)
    
    # Criar mapa
    mapa = folium.Map(
        location=[centro_lat, centro_lon],
        zoom_start=10,
        tiles=obter_tiles_mapa(tema)
    )
    
    # Preparar dados para heatmap
    heat_data = []
    for ponto in dados_coordenadas:
        quantidade = ponto.get('quantidade', 1)
        heat_data.append([ponto['latitude'], ponto['longitude'], quantidade])
    
    # Adicionar heatmap
    HeatMap(heat_data, 
           min_opacity=0.2,
           max_zoom=18,
           radius=25,
           blur=15).add_to(mapa)
    
    return mapa

def criar_mapa_circulos(dados_coordenadas, tema='claro'):
    """Cria mapa com círculos proporcionais às quantidades"""
    # Calcular centro do mapa
    lats = [ponto['latitude'] for ponto in dados_coordenadas]
    lons = [ponto['longitude'] for ponto in dados_coordenadas]
    
    centro_lat = sum(lats) / len(lats)
    centro_lon = sum(lons) / len(lons)
    
    # Criar mapa
    mapa = folium.Map(
        location=[centro_lat, centro_lon],
        zoom_start=10,
        tiles=obter_tiles_mapa(tema)
    )
    
    # Normalizar quantidades para tamanhos de círculo
    quantidades = [ponto.get('quantidade', 1) for ponto in dados_coordenadas]
    min_quantidade = min(quantidades)
    max_quantidade = max(quantidades)
    
    # Função para normalizar tamanho (raio entre 10 e 100)
    def normalizar_raio(quantidade):
        if max_quantidade == min_quantidade:
            return 30
        normalized = (quantidade - min_quantidade) / (max_quantidade - min_quantidade)
        return 10 + (normalized * 90)
    
    # Função para cor baseada na quantidade
    def cor_por_quantidade(quantidade):
        if max_quantidade == min_quantidade:
            return 'blue'
        normalized = (quantidade - min_quantidade) / (max_quantidade - min_quantidade)
        if normalized < 0.33:
            return 'green'
        elif normalized < 0.66:
            return 'orange'
        else:
            return 'red'
    
    # Adicionar círculos
    for ponto in dados_coordenadas:
        quantidade = ponto.get('quantidade', 1)
        raio = normalizar_raio(quantidade)
        cor = cor_por_quantidade(quantidade)
        
        # Criar popup
        popup_html = f"""
        <div style="width: 200px;">
            <h4>{ponto['descricao']}</h4>
            <p><strong>Latitude:</strong> {ponto['latitude']:.6f}</p>
            <p><strong>Longitude:</strong> {ponto['longitude']:.6f}</p>
            <p><strong>Quantidade:</strong> {quantidade}</p>
        </div>
        """
        
        folium.CircleMarker(
            location=[ponto['latitude'], ponto['longitude']],
            radius=raio,
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=f"{ponto['descricao']} ({quantidade})",
            color='white',
            fill=True,
            fillColor=cor,
            fillOpacity=0.7,
            weight=2
        ).add_to(mapa)
    
    return mapa

def criar_mapa_coropletico(dados_estados, tema='claro'):
    """Cria mapa coroplético dos estados brasileiros"""
    try:
        # Criar mapa centrado no Brasil
        mapa = folium.Map(
            location=[-14.235004, -51.92528],  # Centro do Brasil
            zoom_start=4,
            tiles=obter_tiles_mapa(tema)
        )
        
        # Obter GeoJSON dos estados
        geojson_data = obter_geojson_estados()
        
        # Preparar dados para o mapa
        dados_dict = {}
        for item in dados_estados:
            estado_norm = item['estado_normalizado']
            # Tentar mapear para sigla
            sigla = ESTADOS_BRASIL.get(estado_norm, estado_norm.upper())
            dados_dict[sigla] = item['quantidade']
        
        # Calcular min e max para normalização
        valores = list(dados_dict.values())
        min_val = min(valores)
        max_val = max(valores)
        
        # Função para determinar cor baseada no valor
        def obter_cor(valor):
            if valor is None:
                return '#gray'
            
            if max_val == min_val:
                return '#blue'
            
            normalized = (valor - min_val) / (max_val - min_val)
            
            # Escala de cores do verde ao vermelho
            if normalized < 0.2:
                return '#ffffcc'
            elif normalized < 0.4:
                return '#c2e699'
            elif normalized < 0.6:
                return '#78c679'
            elif normalized < 0.8:
                return '#31a354'
            else:
                return '#006837'
        
        # Adicionar camada coroplética
        folium.Choropleth(
            geo_data=geojson_data,
            name='choropleth',
            data=dados_dict,
            columns=['estado', 'quantidade'],
            key_on='feature.properties.sigla',
            fill_color='YlOrRd',
            fill_opacity=0.7,
            line_opacity=0.2,
            legend_name='Quantidade por Estado'
        ).add_to(mapa)
        
        # Adicionar tooltips com informações
        for feature in geojson_data['features']:
            sigla = feature['properties'].get('sigla', '')
            nome = feature['properties'].get('name', sigla)
            valor = dados_dict.get(sigla, 'Sem dados')
            
            tooltip_text = f"{nome} ({sigla}): {valor}"
            
            folium.GeoJson(
                feature,
                style_function=lambda x: {
                    'fillColor': 'transparent',
                    'color': 'transparent',
                    'weight': 0
                },
                tooltip=tooltip_text
            ).add_to(mapa)
        
        return mapa
        
    except Exception as e:
        raise Exception(f"Erro ao criar mapa coroplético: {str(e)}")

def criar_mapa_coordenadas(dados, tipo_mapa='tradicional', tem_quantidade=False, tipo_dados='coordenadas', tema='claro'):
    """Cria mapa baseado no tipo selecionado"""
    try:
        if not dados:
            raise ValueError("Nenhum dado fornecido")
        
        # Para mapas coropléticos
        if tipo_dados == 'coroplético':
            mapa = criar_mapa_coropletico(dados, tema)
        else:
            # Para mapas de coordenadas
            if tipo_mapa == 'tradicional':
                mapa = criar_mapa_tradicional(dados, tema)
            elif tipo_mapa == 'calor' and tem_quantidade:
                mapa = criar_mapa_calor(dados, tema)
            elif tipo_mapa == 'circulos' and tem_quantidade:
                mapa = criar_mapa_circulos(dados, tema)
            elif tipo_mapa == 'coropletico':
                # Fallback para tradicional se não for dados de estado
                mapa = criar_mapa_tradicional(dados, tema)
            else:
                # Fallback para tradicional
                mapa = criar_mapa_tradicional(dados, tema)
        
        # Adicionar estatísticas
        if tipo_dados == 'coroplético':
            stats_html = f"""
            <div style='position: fixed; 
                        top: 10px; right: 10px; width: 220px; height: auto; 
                        background-color: white; border:2px solid grey; z-index:9999; 
                        font-size:14px; padding: 10px'>
            <h4>Estatísticas</h4>
            <p><strong>Total de estados:</strong> {len(dados)}</p>
            <p><strong>Tipo:</strong> Coroplético</p>
            <p><strong>Tema:</strong> {tema.title()}</p>
            """
            
            quantidades = [item['quantidade'] for item in dados]
            total_quantidade = sum(quantidades)
            media_quantidade = total_quantidade / len(quantidades)
            stats_html += f"""
            <p><strong>Total:</strong> {total_quantidade:.1f}</p>
            <p><strong>Média:</strong> {media_quantidade:.1f}</p>
            """
        else:
            # Calcular centro para estatísticas de coordenadas
            lats = [ponto['latitude'] for ponto in dados]
            lons = [ponto['longitude'] for ponto in dados]
            centro_lat = sum(lats) / len(lats)
            centro_lon = sum(lons) / len(lons)
            
            stats_html = f"""
            <div style='position: fixed; 
                        top: 10px; right: 10px; width: 220px; height: auto; 
                        background-color: white; border:2px solid grey; z-index:9999; 
                        font-size:14px; padding: 10px'>
            <h4>Estatísticas</h4>
            <p><strong>Total de pontos:</strong> {len(dados)}</p>
            <p><strong>Tipo:</strong> {tipo_mapa.title()}</p>
            <p><strong>Tema:</strong> {tema.title()}</p>
            """
            
            if tem_quantidade:
                quantidades = [ponto.get('quantidade', 0) for ponto in dados]
                total_quantidade = sum(quantidades)
                media_quantidade = total_quantidade / len(quantidades)
                stats_html += f"""
                <p><strong>Total quantidade:</strong> {total_quantidade:.1f}</p>
                <p><strong>Média:</strong> {media_quantidade:.1f}</p>
                """
            
            stats_html += f"""
            <p><strong>Centro:</strong><br>
            Lat: {centro_lat:.4f}<br>
            Lon: {centro_lon:.4f}</p>
            """
        
        stats_html += "</div>"
        mapa.get_root().html.add_child(folium.Element(stats_html))
        
        return mapa
        
    except Exception as e:
        raise Exception(f"Erro ao criar mapa: {str(e)}")

@app.route('/')
def index():
    """Página principal"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Endpoint para upload e processamento do arquivo Excel"""
    try:
        # Verificar se arquivo foi enviado
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        
        file = request.files['file']
        tipo_mapa = request.form.get('map_type', 'tradicional')
        tema = request.form.get('theme', 'claro')
        
        if file.filename == '':
            return jsonify({'error': 'Nenhum arquivo selecionado'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Tipo de arquivo não permitido. Use .xlsx ou .xls'}), 400
        
        # Salvar arquivo temporário
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
        file.save(filepath)
        
        # Processar Excel
        dados, tem_quantidade, tipo_dados = processar_excel(filepath)
        
        # Validar tipo de mapa
        aviso = None
        if tipo_mapa in ['calor', 'circulos'] and not tem_quantidade:
            tipo_mapa = 'tradicional'
            aviso = "Mapa alterado para tradicional: coluna 'quantidade' não encontrada."
        elif tipo_mapa == 'coropletico' and tipo_dados != 'coroplético':
            tipo_mapa = 'tradicional'
            aviso = "Mapa alterado para tradicional: dados de estados não encontrados."
        
        # Criar mapa
        mapa = criar_mapa_coordenadas(dados, tipo_mapa, tem_quantidade, tipo_dados, tema)
        
        # Salvar mapa HTML
        map_filename = f"mapa_{tipo_mapa}_{tema}_{uuid.uuid4()}.html"
        map_filepath = os.path.join(MAPS_FOLDER, map_filename)
        mapa.save(map_filepath)
        
        # Limpar arquivo temporário
        os.remove(filepath)
        
        response_data = {
            'success': True,
            'message': f'Mapa {tipo_mapa} ({tema}) gerado com sucesso! {len(dados)} pontos processados.',
            'map_url': f'/map/{map_filename}',
            'download_url': f'/download/{map_filename}',
            'points_count': len(dados),
            'map_type': tipo_mapa,
            'theme': tema,
            'data_type': tipo_dados,
            'has_quantity': tem_quantidade
        }
        
        if aviso:
            response_data['warning'] = aviso
        
        return jsonify(response_data)
        
    except Exception as e:
        # Limpar arquivos em caso de erro
        if 'filepath' in locals() and os.path.exists(filepath):
            os.remove(filepath)
        
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500

@app.route('/map/<filename>')
def view_map(filename):
    """Exibe o mapa gerado"""
    try:
        map_filepath = os.path.join(MAPS_FOLDER, filename)
        if not os.path.exists(map_filepath):
            return "Mapa não encontrado", 404
        
        with open(map_filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Erro ao carregar mapa: {str(e)}", 500

@app.route('/download/<filename>')
def download_map(filename):
    """Download do arquivo HTML do mapa"""
    try:
        map_filepath = os.path.join(MAPS_FOLDER, filename)
        if not os.path.exists(map_filepath):
            return "Arquivo não encontrado", 404
        
        return send_file(
            map_filepath,
            as_attachment=True,
            download_name=f"mapa_coordenadas_{filename}",
            mimetype='text/html'
        )
    except Exception as e:
        return f"Erro no download: {str(e)}", 500

@app.route('/exemplo')
def exemplo_excel():
    """Gera um arquivo Excel de exemplo com coordenadas e quantidades"""
    try:
        # Dados de exemplo com quantidades (população aproximada das cidades)
        dados_exemplo = [
            {'latitude': -15.7934, 'longitude': -47.8828, 'descricao': 'Brasília', 'quantidade': 3050000},
            {'latitude': -22.9068, 'longitude': -43.1729, 'descricao': 'Rio de Janeiro', 'quantidade': 6750000},
            {'latitude': -23.5558, 'longitude': -46.6396, 'descricao': 'São Paulo', 'quantidade': 12400000},
            {'latitude': -12.9714, 'longitude': -38.5014, 'descricao': 'Salvador', 'quantidade': 2900000},
            {'latitude': -8.0476, 'longitude': -34.8770, 'descricao': 'Recife', 'quantidade': 1650000},
            {'latitude': -19.9167, 'longitude': -43.9345, 'descricao': 'Belo Horizonte', 'quantidade': 2530000},
            {'latitude': -25.4284, 'longitude': -49.2733, 'descricao': 'Curitiba', 'quantidade': 1950000},
            {'latitude': -30.0346, 'longitude': -51.2177, 'descricao': 'Porto Alegre', 'quantidade': 1490000},
            {'latitude': -3.7319, 'longitude': -38.5267, 'descricao': 'Fortaleza', 'quantidade': 2700000},
            {'latitude': -3.1190, 'longitude': -60.0217, 'descricao': 'Manaus', 'quantidade': 2250000}
        ]
        
        df_exemplo = pd.DataFrame(dados_exemplo)
        
        # Salvar em arquivo temporário
        exemplo_filename = f"exemplo_coordenadas_{uuid.uuid4()}.xlsx"
        exemplo_filepath = os.path.join(UPLOAD_FOLDER, exemplo_filename)
        df_exemplo.to_excel(exemplo_filepath, index=False, engine='openpyxl')
        
        return send_file(
            exemplo_filepath,
            as_attachment=True,
            download_name="exemplo_coordenadas.xlsx",
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        return f"Erro ao gerar exemplo: {str(e)}", 500

@app.route('/exemplo-estados')
def exemplo_estados():
    """Gera um arquivo Excel de exemplo com todos os estados brasileiros e quantidades"""
    try:
        # Dados de todos os estados brasileiros com população aproximada
        dados_estados = [
            {'estado': 'Acre', 'quantidade': 906876},
            {'estado': 'Alagoas', 'quantidade': 3365351},
            {'estado': 'Amapá', 'quantidade': 877613},
            {'estado': 'Amazonas', 'quantidade': 4269995},
            {'estado': 'Bahia', 'quantidade': 14985284},
            {'estado': 'Ceará', 'quantidade': 9240580},
            {'estado': 'Distrito Federal', 'quantidade': 3094325},
            {'estado': 'Espírito Santo', 'quantidade': 4108508},
            {'estado': 'Goiás', 'quantidade': 7206589},
            {'estado': 'Maranhão', 'quantidade': 7153262},
            {'estado': 'Mato Grosso', 'quantidade': 3567234},
            {'estado': 'Mato Grosso do Sul', 'quantidade': 2839188},
            {'estado': 'Minas Gerais', 'quantidade': 21411923},
            {'estado': 'Pará', 'quantidade': 8777124},
            {'estado': 'Paraíba', 'quantidade': 4059905},
            {'estado': 'Paraná', 'quantidade': 11597484},
            {'estado': 'Pernambuco', 'quantidade': 9674793},
            {'estado': 'Piauí', 'quantidade': 3289290},
            {'estado': 'Rio de Janeiro', 'quantidade': 17463349},
            {'estado': 'Rio Grande do Norte', 'quantidade': 3560903},
            {'estado': 'Rio Grande do Sul', 'quantidade': 11466630},
            {'estado': 'Rondônia', 'quantidade': 1815278},
            {'estado': 'Roraima', 'quantidade': 652713},
            {'estado': 'Santa Catarina', 'quantidade': 7338473},
            {'estado': 'São Paulo', 'quantidade': 46649132},
            {'estado': 'Sergipe', 'quantidade': 2338474},
            {'estado': 'Tocantins', 'quantidade': 1607363}
        ]
        
        df_estados = pd.DataFrame(dados_estados)
        
        # Salvar em arquivo temporário
        exemplo_filename = f"exemplo_estados_brasil_{uuid.uuid4()}.xlsx"
        exemplo_filepath = os.path.join(UPLOAD_FOLDER, exemplo_filename)
        df_estados.to_excel(exemplo_filepath, index=False, engine='openpyxl')
        
        return send_file(
            exemplo_filepath,
            as_attachment=True,
            download_name="exemplo_estados_brasil.xlsx",
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        return f"Erro ao gerar exemplo de estados: {str(e)}", 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)