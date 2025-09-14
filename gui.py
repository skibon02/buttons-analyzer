import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Используем backend без GUI
import threading
import time
from pathlib import Path
import glob
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import io
import base64

class WebCSVMonitor:
    def __init__(self):
        # Стили для темной темы
        self.setup_matplotlib_styles()
        
        # Словарь для хранения данных файлов
        self.file_data = {}
        self.max_files = 20
        
        # Загрузка имен
        self.names_file = "names.json"
        self.names = self.load_names()
        
        # Создаем директории
        os.makedirs("samples", exist_ok=True)
        os.makedirs("web_output", exist_ok=True)
        
        # Создаем начальную HTML страницу
        self.generate_initial_html()

        # Запускаем веб-сервер
        self.start_web_server()

        # Запускаем мониторинг в отдельном потоке
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self.monitor_directory, daemon=True)
        self.monitor_thread.start()

    def load_names(self):
        try:
            if os.path.exists(self.names_file):
                with open(self.names_file, 'r', encoding='utf-8') as f:
                    names = json.load(f)
                    # Приводим ключи к строковому типу, если они числовые
                    return {str(k): v for k, v in names.items()}
        except (IOError, json.JSONDecodeError) as e:
            print(f"Ошибка загрузки файла имен: {e}")
        return {}

    def save_names(self):
        try:
            with open(self.names_file, 'w', encoding='utf-8') as f:
                json.dump(self.names, f, indent=4, ensure_ascii=False)
        except IOError as e:
            print(f"Ошибка сохранения файла имен: {e}")

    def rename_session(self, session_id, new_name):
        """Переименование сессии"""
        try:
            self.names[str(session_id)] = new_name
            self.save_names()
            # Принудительно обновляем HTML для отображения нового имени
            self.generate_html_page()
            return True
        except Exception as e:
            print(f"Ошибка переименования сессии: {e}")
            return False

    def setup_matplotlib_styles(self):
        """Настройка стилей для темной темы"""
        plt.style.use('dark_background')
        plt.rcParams['figure.facecolor'] = '#2b2b2b'
        plt.rcParams['axes.facecolor'] = '#363636'
        plt.rcParams['axes.edgecolor'] = '#666666'
        plt.rcParams['axes.labelcolor'] = '#cccccc'
        plt.rcParams['text.color'] = '#cccccc'
        plt.rcParams['xtick.color'] = '#cccccc'
        plt.rcParams['ytick.color'] = '#cccccc'
        plt.rcParams['grid.color'] = '#555555'

    def monitor_directory(self):
        """Мониторинг директории samples"""
        samples_dir = Path("samples")
        processed_files = set()

        while self.monitoring:
            try:
                if samples_dir.exists():
                    # Ищем все CSV файлы с паттернами best_bpm_ur_*.csv и stats_history_*.csv
                    best_files = glob.glob(str(samples_dir / "best_bpm_ur_*.csv"))
                    history_files = glob.glob(str(samples_dir / "stats_history_*.csv"))
                    
                    # Группируем файлы по ID (цифре в названии)
                    file_pairs = self.group_files_by_id(best_files, history_files)
                    
                    # Сортируем по времени изменения
                    file_pairs.sort(key=lambda x: max(
                        os.path.getmtime(x['best']) if x['best'] else 0,
                        os.path.getmtime(x['history']) if x['history'] else 0
                    ), reverse=True)

                    # Проверяем новые или измененные пары файлов
                    updated = False
                    for pair in file_pairs:
                        pair_id = pair['id']
                        if self.should_update_pair(pair, processed_files):
                            self.load_csv_pair(pair)
                            processed_files.add(pair_id)
                            updated = True

                    if updated:
                        self.generate_html_page()

                time.sleep(2)  # Проверяем каждые 2 секунды
            except Exception as e:
                print(f"Ошибка мониторинга: {e}")
                time.sleep(5)

    def group_files_by_id(self, best_files, history_files):
        """Группируем файлы по ID в названии"""
        import re
        pairs = {}
        
        # Обрабатываем best файлы
        for file_path in best_files:
            match = re.search(r'best_bpm_ur_(\d+)\.csv', file_path)
            if match:
                file_id = match.group(1)
                if file_id not in pairs:
                    pairs[file_id] = {'id': file_id, 'best': None, 'history': None}
                pairs[file_id]['best'] = file_path
        
        # Обрабатываем history файлы
        for file_path in history_files:
            match = re.search(r'stats_history_(\d+)\.csv', file_path)
            if match:
                file_id = match.group(1)
                if file_id not in pairs:
                    pairs[file_id] = {'id': file_id, 'best': None, 'history': None}
                pairs[file_id]['history'] = file_path
        
        return list(pairs.values())

    def should_update_pair(self, pair, processed_files):
        """Проверяем нужно ли обновлять пару файлов"""
        pair_id = pair['id']
        if pair_id not in processed_files:
            return True
            
        # Проверяем время модификации файлов
        stored_data = self.file_data.get(pair_id, {})
        current_mtime = 0
        
        if pair['best'] and os.path.exists(pair['best']):
            current_mtime = max(current_mtime, os.path.getmtime(pair['best']))
        if pair['history'] and os.path.exists(pair['history']):
            current_mtime = max(current_mtime, os.path.getmtime(pair['history']))
            
        return stored_data.get('mtime', 0) < current_mtime

    def load_csv_pair(self, pair):
        """Загрузка пары CSV файлов"""
        try:
            pair_id = pair['id']
            print(f"Загружаем пару файлов с ID: {pair_id}")
            
            data = {
                'id': pair_id,
                'best_data': None,
                'history_data': None,
                'mtime': 0,
                'filename': datetime.fromtimestamp(int(pair_id)).strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # Загружаем best файл
            if pair['best'] and os.path.exists(pair['best']):
                best_df = pd.read_csv(pair['best'])
                data['best_data'] = {
                    'bpm_data': best_df[best_df['Type'] == 'BPM'].copy(),
                    'ur_data': best_df[best_df['Type'] == 'UR'].copy(), 
                    'xz_data': best_df[best_df['Type'] == 'ZX'].copy()
                }
                data['mtime'] = max(data['mtime'], os.path.getmtime(pair['best']))
                print(f"Best файл загружен: BPM={len(data['best_data']['bpm_data'])}, UR={len(data['best_data']['ur_data'])}, ZX={len(data['best_data']['xz_data'])}")
            
            # Загружаем history файл
            if pair['history'] and os.path.exists(pair['history']):
                history_df = pd.read_csv(pair['history'])
                data['history_data'] = history_df
                data['mtime'] = max(data['mtime'], os.path.getmtime(pair['history']))
                print(f"History файл загружен: строк={len(history_df)}")
            
            self.file_data[pair_id] = data
            
        except Exception as e:
            print(f"Ошибка загрузки пары {pair_id}: {e}")

    def load_csv_data(self, file_path, mtime):
        """Загрузка данных из CSV файла"""
        try:
            df = pd.read_csv(file_path)
            print(f"Загружен файл: {os.path.basename(file_path)}")
            print(f"Столбцы CSV: {list(df.columns)}")
            print(f"Типы данных: {df['Type'].unique() if 'Type' in df.columns else 'Нет столбца Type'}")
            print(f"Количество строк: {len(df)}")

            # Разделяем данные на BPM, UR и ZX
            bpm_data = df[df['Type'] == 'BPM'].copy()
            ur_data = df[df['Type'] == 'UR'].copy()
            xz_data = df[df['Type'] == 'ZX'].copy()

            print(f"BPM строк: {len(bpm_data)}, UR строк: {len(ur_data)}, ZX строк: {len(xz_data)}")

            self.file_data[file_path] = {
                'bpm_data': bpm_data,
                'ur_data': ur_data,
                'xz_data': xz_data,
                'mtime': mtime,
                'filename': os.path.basename(file_path)
            }
        except Exception as e:
            print(f"Ошибка загрузки {file_path}: {e}")

    def create_plot_image(self, data, filename):
        """Создание изображения графика с 4 подграфиками"""
        print(f"Создаю график для {filename}")
        
        if data.get('best_data'):
            best_data = data['best_data']
            print(f"Best данных: BPM={len(best_data['bpm_data'])}, UR={len(best_data['ur_data'])}, ZX={len(best_data['xz_data'])}")
        if data.get('history_data') is not None:
            print(f"History данных: {len(data['history_data'])} строк")

        try:
            # Создаем фигуру с 4 графиками в layout 2x2
            fig = plt.figure(figsize=(16, 10), facecolor='#2b2b2b')

            # Настраиваем layout для 4 графиков: 2 строки, 2 столбца
            gs = fig.add_gridspec(2, 2, hspace=0.3, wspace=0.3)

            # График 1 (верх-слева): История статистик со скользящим средним
            ax1 = fig.add_subplot(gs[0, 0])
            if data.get('history_data') is not None and not data['history_data'].empty:
                history_df = data['history_data']
                # Определяем какие столбцы есть в данных (поддержка старого и нового формата)
                if 'BPM_avg8' in history_df.columns:
                    bpm_col, ur_col, xz_col = 'BPM_avg8', 'UR_avg8', 'ZX_avg8'
                    avg_window = 8
                else:
                    bpm_col, ur_col, xz_col = 'BPM_avg4', 'UR_avg4', 'ZX_avg4'
                    avg_window = 4
                
                # Фильтруем данные где есть статистики
                stats_data = history_df[history_df[bpm_col] != ''].copy()
                if not stats_data.empty:
                    # Преобразуем строки в числа
                    stats_data[bpm_col] = pd.to_numeric(stats_data[bpm_col])
                    stats_data[ur_col] = pd.to_numeric(stats_data[ur_col])
                    stats_data[xz_col] = pd.to_numeric(stats_data[xz_col])
                    
                    # UR на вторичной оси (рисуем сначала, чтобы был сзади)
                    ax1_ur = ax1.twinx()
                    ax1_ur.plot(stats_data['Press'], stats_data['UR_avg8'], 
                               color='#40e0d0', linewidth=1, label='UR (avg8)', alpha=0.5)
                    
                    # BPM (рисуем поверх UR)
                    ax1.plot(stats_data['Press'], stats_data['BPM_avg8'], 
                            color='#ff69b4', linewidth=2, label='BPM (avg8)', alpha=0.8)
                    
                    # Горизонтальная пунктирная линия среднего BPM
                    avg_bpm = stats_data['BPM_avg8'].mean()
                    ax1.axhline(y=avg_bpm, color='#ff69b4', linestyle='--', linewidth=1.5, alpha=0.7)
                    ax1.text(0.02, avg_bpm + 2, f'Avg: {avg_bpm:.1f} BPM', 
                            transform=ax1.get_yaxis_transform(), 
                            color='#ff69b4', fontsize=12, alpha=0.9, weight='bold')
                    
                    # Display Best UR at max window size
                    if data.get('best_data') and not data['best_data']['ur_data'].empty:
                        best_ur_data = data['best_data']['ur_data']
                        best_ur_at_max_window = best_ur_data.loc[best_ur_data['Window Size'].idxmax()]
                        best_ur_val = best_ur_at_max_window['UR']
                        
                        ax1_ur.axhline(y=best_ur_val, color='#40e0d0', linestyle='--', linewidth=1.5, alpha=0.7)
                        ax1_ur.text(0.98, best_ur_val + 5, f'Best UR (max win): {best_ur_val:.1f}',
                                   transform=ax1_ur.get_yaxis_transform(),
                                   color='#40e0d0', fontsize=12, alpha=0.9, weight='bold',
                                   horizontalalignment='right')
                    else:
                        # Fallback to mean if no best UR data is available
                        avg_ur = stats_data['UR_avg8'].mean()
                        ax1_ur.axhline(y=avg_ur, color='#40e0d0', linestyle='--', linewidth=1.5, alpha=0.7)
                        ax1_ur.text(0.98, avg_ur + 5, f'Avg: {avg_ur:.1f} UR', 
                                   transform=ax1_ur.get_yaxis_transform(), 
                                   color='#40e0d0', fontsize=12, alpha=0.9, weight='bold',
                                   horizontalalignment='right')
                    
                    # Устанавливаем скейл BPM
                    bpm_max = max(280, stats_data['BPM_avg8'].max() * 1.1) if not stats_data['BPM_avg8'].empty else 280
                    ax1.set_ylim(0, bpm_max)
                    
                    # Устанавливаем скейл UR (до 300, больше игнорируем)
                    ax1_ur.set_ylim(0, 300)
                    ax1_ur.set_ylabel('UR', color='#40e0d0', fontsize=9)
                    ax1_ur.tick_params(axis='y', labelcolor='#40e0d0', labelsize=7)
            
            ax1.set_xlabel('Button Press #', color='#cccccc', fontsize=10)
            ax1.set_ylabel('BPM', color='#ff69b4', fontsize=10)
            ax1.set_title('STATS HISTORY (Moving Avg 8)', color='#ffaa44', fontsize=12, pad=10, weight='bold')
            ax1.grid(True, alpha=0.3)
            ax1.set_facecolor('#363636')
            ax1.tick_params(labelsize=8, colors='#cccccc')

            # График 2 (верх-справа): Сырые интервалы между нажатиями
            ax2 = fig.add_subplot(gs[0, 1])
            if data.get('history_data') is not None and not data['history_data'].empty:
                history_df = data['history_data']
                # Рисуем сырые интервалы
                ax2.plot(history_df['Press'], history_df['Interval_ms'], 
                        color='#88ccff', linewidth=1.5, alpha=0.7, marker='.', markersize=3)
                
                # Устанавливаем скейл интервалов
                ax2.set_ylim(0, 200)
                
                # Добавляем ZX баланс на вторичной оси (только где есть данные)
                # Определяем какие столбцы есть в данных
                if 'ZX_avg8' in history_df.columns:
                    xz_col = 'ZX_avg8'
                else:
                    xz_col = 'ZX_avg4'
                    
                stats_data = history_df[history_df[xz_col] != ''].copy()
                if not stats_data.empty:
                    stats_data[xz_col] = pd.to_numeric(stats_data[xz_col])
                    ax2_xz = ax2.twinx()
                    ax2_xz.plot(stats_data['Press'], stats_data[xz_col], 
                               color='#cc8800', linewidth=2, alpha=0.8)
                    
                    # Устанавливаем симметричный скейл ZX
                    xz_abs_max = max(20, abs(stats_data[xz_col]).max() * 1.1) if not stats_data[xz_col].empty else 20
                    ax2_xz.set_ylim(-xz_abs_max, xz_abs_max)
                    ax2_xz.set_ylabel('ZX %', color='#cc8800', fontsize=9)
                    ax2_xz.tick_params(axis='y', labelcolor='#cc8800', labelsize=7)
            
            ax2.set_xlabel('Button Press #', color='#cccccc', fontsize=10)
            ax2.set_ylabel('Interval (ms)', color='#88ccff', fontsize=10)
            ax2.set_title('RAW INTERVALS', color='#ffaa44', fontsize=12, pad=10, weight='bold')
            ax2.grid(True, alpha=0.3)
            ax2.set_facecolor('#363636')
            ax2.tick_params(labelsize=8, colors='#cccccc')

            # График 3 (низ-слева): Лучший BPM с ZX
            ax3 = fig.add_subplot(gs[1, 0])
            if data.get('best_data') and not data['best_data']['bpm_data'].empty:
                best_data = data['best_data']
                ax3.plot(best_data['bpm_data']['Window Size'],
                        best_data['bpm_data']['BPM'],
                        color='#ff69b4',
                        linewidth=2,
                        marker='o',
                        markersize=4)
                
                # Устанавливаем скейл BPM
                bpm_max = max(280, best_data['bpm_data']['BPM'].max() * 1.1) if not best_data['bpm_data'].empty else 280
                ax3.set_ylim(0, bpm_max)
                
                # Добавляем ZX как вторичную метрику
                if 'ZX' in best_data['bpm_data'].columns:
                    ax3_xz = ax3.twinx()
                    ax3_xz.plot(best_data['bpm_data']['Window Size'],
                               best_data['bpm_data']['ZX'],
                               color='#cc8800',
                               linewidth=1.5,
                               marker='s',
                               markersize=3,
                               alpha=0.7)
                    
                    # Устанавливаем симметричный скейл ZX
                    xz_abs_max = max(20, abs(best_data['bpm_data']['ZX']).max() * 1.1) if not best_data['bpm_data']['ZX'].empty else 20
                    ax3_xz.set_ylim(-xz_abs_max, xz_abs_max)
                    ax3_xz.set_ylabel('ZX %', color='#cc8800', fontsize=9)
                    ax3_xz.tick_params(axis='y', labelcolor='#cc8800', labelsize=7)
            
            ax3.set_xlabel('Window Size', color='#cccccc', fontsize=10)
            ax3.set_ylabel('Best BPM', color='#ff69b4', fontsize=10)
            ax3.set_title('BEST BPM Distribution', color='#ffaa44', fontsize=12, pad=10, weight='bold')
            ax3.grid(True, alpha=0.3)
            ax3.set_facecolor('#363636')
            ax3.tick_params(labelsize=8, colors='#cccccc')
            
            # График 4 (низ-справа): Лучший UR с ZX
            ax4 = fig.add_subplot(gs[1, 1])
            if data.get('best_data') and not data['best_data']['ur_data'].empty:
                best_data = data['best_data']
                ax4.plot(best_data['ur_data']['Window Size'],
                        best_data['ur_data']['UR'],
                        color='#40e0d0',
                        linewidth=2,
                        marker='o',
                        markersize=4)
                
                # Устанавливаем скейл UR
                ur_max = max(250, best_data['ur_data']['UR'].max() * 1.1) if not best_data['ur_data'].empty else 250
                ax4.set_ylim(0, ur_max)
                
                # Добавляем ZX как вторичную метрику
                if 'ZX' in best_data['ur_data'].columns:
                    ax4_xz = ax4.twinx()
                    ax4_xz.plot(best_data['ur_data']['Window Size'],
                               best_data['ur_data']['ZX'],
                               color='#cc8800',
                               linewidth=1.5,
                               marker='s',
                               markersize=3,
                               alpha=0.7)
                    
                    # Устанавливаем симметричный скейл ZX
                    xz_abs_max = max(20, abs(best_data['ur_data']['ZX']).max() * 1.1) if not best_data['ur_data']['ZX'].empty else 20
                    ax4_xz.set_ylim(-xz_abs_max, xz_abs_max)
                    ax4_xz.set_ylabel('ZX %', color='#cc8800', fontsize=9)
                    ax4_xz.tick_params(axis='y', labelcolor='#cc8800', labelsize=7)
            
            ax4.set_xlabel('Window Size', color='#cccccc', fontsize=10)
            ax4.set_ylabel('Best UR', color='#40e0d0', fontsize=10)
            ax4.set_title('BEST UR Distribution', color='#ffaa44', fontsize=12, pad=10, weight='bold')
            ax4.grid(True, alpha=0.3)
            ax4.set_facecolor('#363636')
            ax4.tick_params(labelsize=8, colors='#cccccc')

            # Добавляем общий заголовок
            fig.suptitle(f"{filename}", color='#cccccc', fontsize=14, y=0.95, weight='bold')

            # Сохраняем в base64 для встраивания в HTML
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', facecolor='#2b2b2b', bbox_inches='tight', dpi=100)
            buffer.seek(0)
            plot_data = buffer.getvalue()
            buffer.close()
            plt.close(fig)

            print(f"График создан успешно, размер: {len(plot_data)} байт")
            return base64.b64encode(plot_data).decode()

        except Exception as e:
            print(f"Ошибка создания графика: {e}")
            return ""

    def generate_initial_html(self):
        """Создание начальной HTML страницы"""
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="cache-control" content="no-cache">
    <meta http-equiv="expires" content="0">
    <meta http-equiv="pragma" content="no-cache">
    <title>BPM/UR Stats Monitor</title>
    <style>
        body {{
            background-color: #2b2b2b;
            color: #cccccc;
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            text-align: center;
        }}
        .header {{
            margin-bottom: 30px;
        }}
        .waiting {{
            background-color: #363636;
            border-radius: 10px;
            padding: 30px;
            margin: 20px auto;
            max-width: 600px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.3);
        }}
        .bpm-color {{ color: #ff69b4; }}
        .ur-color {{ color: #40e0d0; }}
        .xz-color {{ color: #cc8800; }}
        .loading {{
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
            100% {{ opacity: 1; }}
        }}
        .delete-btn {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: #d32f2f;
            color: white;
            border: none;
            border-radius: 3px;
            padding: 5px 8px;
            font-size: 12px;
            cursor: pointer;
            opacity: 0.7;
            transition: opacity 0.3s;
        }}
        .delete-btn:hover {{
            opacity: 1;
        }}
        .plot-container {{
            position: relative;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 BPM/UR Stats Monitor</h1>
        <p><span class="bpm-color">● BPM Performance</span> | <span class="ur-color">● UR Performance</span> | <span class="xz-color">● ZX Balance</span></p>
    </div>

    <div class="waiting">
        <h2 class="loading">Ожидание данных...</h2>
        <p>Мониторинг папки <code>samples/</code></p>
        <p>Запустите вашу Rust программу для генерации CSV файлов</p>
        <p>Страница обновляется автоматически каждые 2 секунды</p>
        <p style="margin-top: 20px; color: #888; font-size: 0.9em;">
            Время запуска: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        </p>
    </div>
</body>
</html>
"""

        # Сохраняем HTML файл
        with open("web_output/index.html", "w", encoding="utf-8") as f:
            f.write(html_content)

    def generate_html_page(self):
        """Генерация HTML страницы"""
        # Сортируем файлы по времени изменения (новые сверху)
        sorted_files = sorted(self.file_data.items(),
                            key=lambda x: x[1]['mtime'],
                            reverse=True)

        # Ограничиваем количество отображаемых файлов
        files_to_show = sorted_files[:self.max_files]

        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="cache-control" content="no-cache">
    <meta http-equiv="expires" content="0">
    <meta http-equiv="pragma" content="no-cache">
    <title>BPM/UR Stats Monitor</title>
    <style>
        body {{
            background-color: #2b2b2b;
            color: #cccccc;
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }}
        @media (max-width: 1400px) {{
            .grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .plot-container {{
            background-color: #363636;
            border-radius: 10px;
            padding: 15px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.3);
            position: relative;
        }}
        .plot-image {{
            width: 100%;
            height: auto;
            border-radius: 5px;
        }}
        .timestamp {{
            font-size: 0.8em;
            color: #888;
            margin-top: 10px;
            text-align: center;
        }}
        .stats {{
            background-color: #404040;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 15px;
            text-align: center;
        }}
        .bpm-color {{ color: #ff69b4; }}
        .ur-color {{ color: #40e0d0; }}
        .xz-color {{ color: #cc8800; }}
        .plot-title {{
            text-align: center;
            margin: 5px 0 10px 0;
            padding: 5px;
            border-radius: 3px;
            transition: background-color 0.3s;
        }}
        .plot-title:hover {{
            background-color: #444;
        }}
        .plot-title:focus {{
            background-color: #555;
            outline: none;
        }}
        .delete-btn {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: #d32f2f;
            color: white;
            border: none;
            border-radius: 3px;
            padding: 5px 8px;
            font-size: 12px;
            cursor: pointer;
            opacity: 0.7;
            transition: opacity 0.3s;
        }}
        .delete-btn:hover {{
            opacity: 1;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 BPM/UR Stats Monitor</h1>
        <div class="stats">
            <span class="bpm-color">● BPM Performance</span> |
            <span class="ur-color">● UR Performance</span> |
            <span class="xz-color">● ZX Balance</span> | 
            Обновлено: {datetime.now().strftime("%H:%M:%S")} | 
            Файлов: {len(files_to_show)} | v{int(datetime.now().timestamp())}
        </div>
    </div>
    
    <div class="grid" id="plots-container">
        <div class="waiting">
            <h2 class="loading">Загрузка данных...</h2>
            <p>Ожидание графиков</p>
        </div>
    </div>
    
    <script>
        let lastVersion = 0;

        function selectText(element) {{
            const range = document.createRange();
            range.selectNodeContents(element);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        }}
        
        async function updateData() {{
            try {{
                const response = await fetch('/api/data');
                const data = await response.json();

                if (data.version <= lastVersion) {{
                    return; // No changes, do nothing
                }}
                lastVersion = data.version;

                // Remove waiting message
                const waitingDiv = document.querySelector('.waiting');
                if (waitingDiv) {{
                    waitingDiv.remove();
                }}

                // Update header stats
                document.querySelector('.stats').innerHTML = `
                    <span class="bpm-color">● BPM Performance</span> |
                    <span class="ur-color">● UR Performance</span> |
                    <span class="xz-color">● ZX Balance</span> | 
                    Обновлено: ${{data.timestamp}} | 
                    Файлов: ${{data.files_count}} | v${{data.version}}
                `;

                const grid = document.getElementById('plots-container');
                const newPlotIds = new Set(data.plots.map(p => p.id));

                // Remove old plots
                for (const plotDiv of grid.querySelectorAll('.plot-container')) {{
                    const plotId = plotDiv.dataset.plotId;
                    if (!newPlotIds.has(plotId)) {{
                        grid.removeChild(plotDiv);
                    }}
                }}

                // Add or update plots, and ensure correct order
                data.plots.reverse().forEach(plot => {{ // Iterate oldest to newest
                    let plotDiv = grid.querySelector(`[data-plot-id="${{plot.id}}"]`);
                    if (plotDiv) {{
                        // Plot exists, check if it needs updating
                        const existingTimestamp = plotDiv.dataset.timestamp;
                        if (existingTimestamp !== plot.timestamp) {{
                            // Update image and timestamp
                            plotDiv.querySelector('.plot-image').src = `data:image/png;base64,${{plot.image}}`;
                            plotDiv.querySelector('.timestamp').innerText = `Создан: ${{plot.timestamp}}`;
                            plotDiv.dataset.timestamp = plot.timestamp;
                        }}
                    }} else {{
                        // New plot, create it
                        plotDiv = document.createElement('div');
                        plotDiv.className = 'plot-container';
                        plotDiv.dataset.plotId = plot.id;
                        plotDiv.dataset.timestamp = plot.timestamp;
                        plotDiv.innerHTML = `
                            <h3 class="plot-title" contenteditable="true" onblur="renameSession('${{plot.id}}', this.innerText)" onfocus="selectText(this)">${{plot.name}}</h3>
                            <button class="delete-btn" onclick="deleteSession('${{plot.id}}')" title="Удалить сессию">✗</button>
                            <img class="plot-image" src="data:image/png;base64,${{plot.image}}" alt="Plot for ${{plot.filename}}">
                            <div class="timestamp">Создан: ${{plot.timestamp}}</div>
                        `;
                    }}
                    // Move to top
                    grid.insertBefore(plotDiv, grid.firstChild);
                }});

            }} catch (error) {{
                console.error('Ошибка обновления данных:', error);
            }}
        }}
        
        // Функция переименования сессии
        async function renameSession(sessionId, newName) {{
            try {{
                const response = await fetch(`/api/rename/${{sessionId}}`, {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                    }},
                    body: JSON.stringify({{ name: newName }}),
                }});
                if (response.ok) {{
                    console.log(`Сессия ${{sessionId}} переименована в ${{newName}}`);
                }} else {{
                    alert('Ошибка переименования сессии');
                }}
            }} catch (error) {{
                console.error('Ошибка при переименовании:', error);
                alert('Ошибка переименования сессии');
            }}
        }}

        // Функция удаления сессии
        async function deleteSession(sessionId) {{
            if (!confirm('Вы уверены, что хотите удалить эту сессию?')) {{
                return;
            }}
            
            try {{
                const response = await fetch(`/api/delete/${{sessionId}}`);
                if (response.ok) {{
                    console.log(`Сессия ${{sessionId}} удалена`);
                    // Принудительно обновляем данные
                    lastVersion = 0;
                    updateData();
                }} else {{
                    alert('Ошибка удаления сессии');
                }}
            }} catch (error) {{
                console.error('Ошибка при удалении:', error);
                alert('Ошибка удаления сессии');
            }}
        }}
        
        // Обновляем каждые 2 секунды
        setInterval(updateData, 2000);
        
        // Первичная загрузка
        updateData();
    </script>
</body>
</html>
"""
        
        # Сохраняем HTML файл
        with open("web_output/index.html", "w", encoding="utf-8") as f:
            f.write(html_content)
            
    def generate_json_data(self):
        """Генерация JSON данных для AJAX"""
        sorted_files = sorted(self.file_data.items(),
                            key=lambda x: x[1]['mtime'],
                            reverse=True)
        files_to_show = sorted_files[:self.max_files]
        
        data = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "files_count": len(files_to_show),
            "version": int(datetime.now().timestamp()),
            "plots": []
        }
        
        for file_path, file_data in files_to_show:
            try:
                session_id = file_data['id']
                # Получаем имя из словаря или используем стандартное
                custom_name = self.names.get(str(session_id), file_data['filename'])

                plot_base64 = self.create_plot_image(file_data, custom_name)
                mtime_str = datetime.fromtimestamp(file_data['mtime']).strftime("%Y-%m-%d %H:%M:%S")
                
                data["plots"].append({
                    "id": session_id,
                    "filename": file_data['filename'], # original filename
                    "name": custom_name, # custom name
                    "image": plot_base64,
                    "timestamp": mtime_str
                })
            except Exception as e:
                print(f"Ошибка создания графика для {file_data['filename']}: {e}")
        
        return json.dumps(data)

    def delete_files_by_id(self, file_id):
        """Безопасное удаление файлов по ID"""
        import os
        import re
        
        try:
            # Дополнительная валидация ID
            if not re.match(r'^\d{10,15}$', file_id):
                print(f"Invalid file ID format: {file_id}")
                return False
            
            samples_dir = Path("samples")
            if not samples_dir.exists():
                return False
            
            # Формируем точные имена файлов с валидацией
            best_file = samples_dir / f"best_bpm_ur_{file_id}.csv"
            history_file = samples_dir / f"stats_history_{file_id}.csv"
            
            deleted_count = 0
            
            # Удаляем файлы если они существуют
            for file_path in [best_file, history_file]:
                if file_path.exists() and file_path.is_file():
                    # Дополнительная проверка: файл должен быть именно в samples/
                    if file_path.parent.name == "samples" and file_path.suffix == ".csv":
                        os.remove(file_path)
                        deleted_count += 1
                        print(f"Deleted: {file_path}")
            
            # Удаляем из кэша
            if file_id in self.file_data:
                del self.file_data[file_id]
            
            return deleted_count > 0
            
        except Exception as e:
            print(f"Error in delete_files_by_id: {e}")
            return False

    def start_web_server(self):
        """Запуск веб-сервера"""
        server_port = 8000
        monitor_ref = self
        
        try:
            class CustomHandler(SimpleHTTPRequestHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory="web_output", **kwargs)
                
                def do_GET(self):
                    parsed_path = urlparse(self.path)
                    if parsed_path.path == '/api/data':
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        json_data = monitor_ref.generate_json_data()
                        self.wfile.write(json_data.encode())
                    elif parsed_path.path.startswith('/api/delete/'):
                        # Безопасное удаление файлов по ID
                        try:
                            file_id = parsed_path.path.split('/')[-1]
                            # Валидация: только цифры, защита от path traversal
                            if not file_id.isdigit() or len(file_id) > 15:
                                self.send_response(400)
                                self.end_headers()
                                self.wfile.write(b'Invalid file ID')
                                return
                            
                            success = monitor_ref.delete_files_by_id(file_id)
                            if success:
                                self.send_response(200)
                                self.send_header('Content-type', 'application/json')
                                self.end_headers()
                                self.wfile.write(b'{"status": "deleted"}')
                            else:
                                self.send_response(404)
                                self.end_headers()
                                self.wfile.write(b'Files not found')
                        except Exception as e:
                            print(f"Error deleting files: {e}")
                            self.send_response(500)
                            self.end_headers()
                            self.wfile.write(b'Internal server error')
                    else:
                        super().do_GET()
                
                def do_POST(self):
                    parsed_path = urlparse(self.path)
                    if parsed_path.path.startswith('/api/rename/'):
                        try:
                            session_id = parsed_path.path.split('/')[-1]
                            if not session_id.isdigit() or len(session_id) > 15:
                                self.send_response(400)
                                self.end_headers()
                                self.wfile.write(b'Invalid session ID')
                                return

                            content_length = int(self.headers['Content-Length'])
                            post_data = self.rfile.read(content_length)
                            data = json.loads(post_data)
                            new_name = data.get('name')

                            if not new_name:
                                self.send_response(400)
                                self.end_headers()
                                self.wfile.write(b'Name is required')
                                return

                            success = monitor_ref.rename_session(session_id, new_name)
                            if success:
                                self.send_response(200)
                                self.send_header('Content-type', 'application/json')
                                self.end_headers()
                                self.wfile.write(b'{"status": "renamed"}')
                            else:
                                self.send_response(500)
                                self.end_headers()
                                self.wfile.write(b'Internal server error')

                        except Exception as e:
                            print(f"Error renaming session: {e}")
                            self.send_response(500)
                            self.end_headers()
                            self.wfile.write(b'Internal server error')
                    else:
                        self.send_response(404)
                        self.end_headers()
            
            httpd = HTTPServer(('localhost', server_port), CustomHandler)
            server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            server_thread.start()
            
            print(f"Веб-сервер запущен на http://localhost:{server_port}")
            print("Откройте браузер и перейдите по указанному адресу")
            
            # Автоматически открываем браузер
            try:
                webbrowser.open(f'http://localhost:{server_port}')
            except:
                pass
                
        except Exception as e:
            print(f"Ошибка запуска веб-сервера: {e}")
    
    def run(self):
        """Запуск мониторинга"""
        print("Мониторинг запущен...")
        print("Нажмите Ctrl+C для выхода")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nЗавершение работы...")
            self.monitoring = False

if __name__ == "__main__":
    monitor = WebCSVMonitor()
    monitor.run()