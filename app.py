import streamlit as st
import requests
import json
import pandas as pd
from datetime import datetime
import os
from dotenv import load_dotenv
import io # ファイルダウンロード用に必要

# .envファイルから環境変数を読み込む
load_dotenv()

# 環境変数から設定値を取得
# Streamlitアプリでは環境変数を直接UIで設定するか、.envから読み込む
# ここでは.envを優先するが、UIでの設定も考慮する
REQUEST_URL = os.getenv('REQUEST_URL', 'https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData') # デフォルトURL追加
APP_ID = os.getenv('APP_ID')

# --- Streamlit UI ---
st.title('通関統計データ取得アプリ')

# 環境変数APP_IDがない場合の入力
if not APP_ID:
    APP_ID = st.text_input("e-Stat API アプリケーションIDを入力してください:", type="password")

# 1. 年の指定
current_year = datetime.now().year
selected_year = st.number_input('取得するデータの年（西暦4桁）を入力してください:', min_value=1988, max_value=current_year + 1, value=current_year)

# 2. HSコードファイルのアップロード
uploaded_file = st.file_uploader("HSコード一覧のCSVファイルを選択してください (ヘッダー名: 'HSコード')", type='csv')

# 実行ボタン
if st.button('データ取得・処理実行'):
    if not APP_ID:
        st.error("APIアプリケーションIDが設定されていません。")
    elif uploaded_file is None:
        st.error("HSコード一覧ファイルをアップロードしてください。")
    else:
        # cdTimeを生成 (YYYY000000形式)
        cd_time = f"{selected_year}000000"

        # APIパラメータの準備
        params = {
            'cdTime': cd_time,
            'appId': APP_ID,
            'lang': 'J',
            'statsDataId': '0004002161',  # 統計表ID
            'metaGetFlg': 'Y',
            'cntGetFlg': 'N',
            'explanationGetFlg': 'Y',
            'annotationGetFlg': 'Y',
            'sectionHeaderFlg': '1',
            'replaceSpChars': '0'
        }

        # HSコード一覧の読み込み
        try:
            # アップロードされたファイルをメモリ上で読み込む
            # 文字コードは自動判別を試みるか、固定にする (ここではcp932を仮定)
            try:
                df_hscode = pd.read_csv(uploaded_file, encoding='cp932', dtype={'HSコード': str}) # HSコードを文字列として読み込む
            except UnicodeDecodeError:
                st.warning("cp932での読み込みに失敗しました。utf-8で再試行します。")
                # StringIOを使ってファイルを再度読み込む準備
                uploaded_file.seek(0) # ファイルポインタを先頭に戻す
                stringio = io.StringIO(uploaded_file.getvalue().decode('utf-8'))
                df_hscode = pd.read_csv(stringio, dtype={'HSコード': str})
            except Exception as e:
                st.error(f"HSコード一覧CSVの読み込み中に予期せぬエラーが発生しました: {e}")
                st.stop() # エラーがあれば処理中断

            if 'HSコード' not in df_hscode.columns:
                st.error("アップロードされたCSVに 'HSコード' という列が見つかりません。")
                st.stop()

            hs_codes = df_hscode['HSコード'].unique().tolist() # 重複を除外
            hs_codes = [code for code in hs_codes if pd.notna(code) and code.strip()] # NaNや空文字を除外
            if not hs_codes:
                st.error("HSコード一覧ファイルに有効なHSコードが見つかりません。")
                st.stop()

            st.write(f"読み込んだHSコード数: {len(hs_codes)}")

        except Exception as e:
            st.error(f"HSコード一覧ファイルの処理中にエラーが発生しました: {e}")
            st.stop() # エラーがあれば処理中断

        # --- データ取得・処理 (既存のmain関数のロジックをここに統合・調整) ---
        data_list = []
        result = None
        processed_count = 0
        error_count = 0
        skipped_count = 0

        progress_bar = st.progress(0)
        status_text = st.empty()

        st.info("APIからデータを取得しています...")
        for i, code in enumerate(hs_codes):
            status_text.text(f"HSコード: {code} ({i+1}/{len(hs_codes)}) を処理中...")
            params['cdCat01'] = str(code) # HSコードを文字列に変換
            try:
                res = requests.get(REQUEST_URL, params)
                res.raise_for_status()
                result_json = res.json() # APIレスポンスを格納

                # --- レスポンスチェックとデータ抽出 (既存コードを流用・ปรับปรุง) ---
                if 'GET_STATS_DATA' not in result_json:
                    st.warning(f"警告: HSコード {code} のレスポンス形式が不正です。スキップします。")
                    skipped_count += 1
                    continue

                api_result = result_json['GET_STATS_DATA']

                if 'RESULT' not in api_result or 'STATUS' not in api_result['RESULT']:
                    st.warning(f"警告: HSコード {code} のレスポンスに結果ステータスが含まれていません。スキップします。")
                    skipped_count += 1
                    continue

                status = api_result['RESULT']['STATUS']

                if status == 0:
                    if 'STATISTICAL_DATA' in api_result and 'DATA_INF' in api_result['STATISTICAL_DATA'] and 'VALUE' in api_result['STATISTICAL_DATA']['DATA_INF']:
                        response_value = api_result['STATISTICAL_DATA']['DATA_INF']['VALUE']
                        for row in response_value:
                            data_list.append(row)
                        # 正常処理された最後の有効なレスポンスを保持 (メタデータ用)
                        result = result_json
                        processed_count += 1
                    else:
                        # データなしでも警告は出す
                        if 'ERROR_MSG' in api_result['RESULT']:
                             st.warning(f"  情報(HS:{code}): {api_result['RESULT']['ERROR_MSG']}")
                        else:
                             st.warning(f"  情報(HS:{code}): データ(VALUE)が見つかりませんでした。")
                        skipped_count += 1

                else: # status != 0 (APIエラー)
                    error_msg = api_result['RESULT'].get('ERROR_MSG', '不明なエラー')
                    st.warning(f"警告: HSコード {code} の取得でAPIエラー (STATUS: {status}, MSG: {error_msg})。スキップします。")
                    error_count += 1
                    continue

            except requests.exceptions.RequestException as e:
                st.error(f"エラー: HSコード {code} の取得中に通信エラー: {e}")
                error_count += 1
                continue
            except json.JSONDecodeError:
                st.error(f"エラー: HSコード {code} のAPIレスポンスがJSON形式ではありません。")
                error_count += 1
                continue
            except Exception as e:
                st.error(f"エラー: HSコード {code} の処理中に予期せぬエラー: {e}")
                error_count += 1
                continue
            finally:
                # プログレスバー更新
                progress_bar.progress((i + 1) / len(hs_codes))

        status_text.text("データ取得完了。データを処理しています...")

        if not data_list:
            st.error("有効なデータが一件も取得できませんでした。")
            st.stop()

        df = pd.DataFrame(data_list)
        df.rename(columns={
            '@cat01': 'HSコード', '@cat02': '区分コード', '@cat03': '税関コード',
            '@area': '国コード', '@time': '年コード', '$': '値（金額、数量）',
            '@unit': '単位'
        }, inplace=True)

        # --- メタデータ処理 (既存コードを流用・ปรับปรุง) ---
        df_complete = df # メタデータ取得失敗時のデフォルト

        if result is None:
             st.warning("メタデータの取得に必要な有効なAPIレスポンスがありませんでした。メタデータなしで処理を続行します。")
        elif 'GET_STATS_DATA' not in result or 'STATISTICAL_DATA' not in result['GET_STATS_DATA'] or 'CLASS_INF' not in result['GET_STATS_DATA']['STATISTICAL_DATA']:
             st.warning("APIレスポンスからメタデータ(CLASS_INF)が見つかりませんでした。メタデータなしで処理を続行します。")
        else:
            try:
                class_objs = result['GET_STATS_DATA']['STATISTICAL_DATA']['CLASS_INF']['CLASS_OBJ']

                df_cat02_shrink = pd.DataFrame(columns=['区分コード', '区分名', '親コード'])
                df_zeikan_shrink = pd.DataFrame(columns=['税関コード', '税関'])
                df_country_shrink = pd.DataFrame(columns=['国コード', '国名'])

                # 区分コード(cat02)
                cat02_obj = next((obj for obj in class_objs if obj['@id'] == 'cat02'), None)
                if cat02_obj and 'CLASS' in cat02_obj:
                    df_cat02 = pd.DataFrame(cat02_obj['CLASS'])
                    df_cat02.rename(columns={'@code': '区分コード', '@name': '区分名', '@parentCode': '親コード'}, inplace=True)
                    df_cat02_shrink = df_cat02[['区分コード', '区分名', '親コード']]
                else:
                    st.warning("区分コード(cat02)のメタデータが見つかりません。")

                # 税関コード(cat03)
                cat03_obj = next((obj for obj in class_objs if obj['@id'] == 'cat03'), None)
                if cat03_obj and 'CLASS' in cat03_obj:
                    df_zeikan = pd.DataFrame(cat03_obj['CLASS'])
                    df_zeikan.rename(columns={'@code': '税関コード', '@name': '税関'}, inplace=True)
                    df_zeikan_shrink = df_zeikan[['税関コード', '税関']]
                else:
                    st.warning("税関コード(cat03)のメタデータが見つかりません。")

                # 国コード(area)
                area_obj = next((obj for obj in class_objs if obj['@id'] == 'area'), None)
                if area_obj and 'CLASS' in area_obj:
                    df_country = pd.DataFrame(area_obj['CLASS'])
                    df_country.rename(columns={'@code': '国コード', '@name': '国名'}, inplace=True)
                    df_country_shrink = df_country[['国コード', '国名']]
                    # 国名からコード部分を削除
                    df_country_shrink['国名'] = df_country_shrink['国名'].astype(str).str.split('_', n=1).str[1]
                else:
                     st.warning("国コード(area)のメタデータが見つかりません。")


                # データのマージ
                st.write("データをマージしています...")
                df_merged_1 = pd.merge(df, df_cat02_shrink, on='区分コード', how='left')
                df_merged_2 = pd.merge(df_merged_1, df_zeikan_shrink, on='税関コード', how='left')
                df_merged_3 = pd.merge(df_merged_2, df_country_shrink, on='国コード', how='left')
                df_merged_3['年'] = df_merged_3['年コード'].astype(str).str.slice(0, 4)
                df_merged_3['年'] = pd.to_numeric(df_merged_3['年'], errors='coerce').astype('Int64')

                # HSコードとのマージ (df_hscodeの型を合わせる)
                df_merged_3['HSコード'] = df_merged_3['HSコード'].astype(str)
                # アップロードされたhsコードデータフレームも文字列に
                df_hscode_merge = df_hscode[['HSコード', '品目']].astype(str).drop_duplicates(subset=['HSコード'])
                df_merged_4 = pd.merge(df_merged_3, df_hscode_merge, on='HSコード', how='left')

                df_complete = df_merged_4
            except Exception as e:
                 st.error(f"データマージ中にエラーが発生しました: {e}")
                 st.warning("マージ前のデータを使用します。")
                 df_complete = df # エラー時はマージ前のデータ

        # --- データ整形 (既存コードを流用・調整) ---
        st.write("データを整形しています...")
        try:
            required_cols = ['HSコード', '品目', '年', '区分名', '国コード', '国名', '税関コード', '税関', '値（金額、数量）', '単位']
            available_cols = [col for col in required_cols if col in df_complete.columns] # 存在する必須列
            missing_cols = [col for col in required_cols if col not in df_complete.columns] # 不足している必須列

            if missing_cols:
                st.warning(f"必要な列が不足しているため、一部の整形処理ができません。不足列: {missing_cols}")

            # 区分名が存在する場合のみフィルタリングと整形
            if '区分名' in df_complete.columns:
                 df_complete = df_complete.dropna(subset=['区分名'])
                 exclude_values = ['単位2', '合計_金額', '合計_数量1', '合計_数量2']
                 df_complete = df_complete[~df_complete['区分名'].isin(exclude_values)]

                 split_cols = df_complete['区分名'].astype(str).str.split('_', expand=True, n=1)
                 df_complete['月'] = split_cols[0] if 0 in split_cols else pd.NA
                 df_complete['区分'] = split_cols[1] if 1 in split_cols else pd.NA

                 # 年月の日付データ作成
                 df_complete['月数値'] = df_complete['月'].str.extract(r'(\d+)').astype('Int64')
                 # 年と月数値の両方が有効な行のみを対象とする
                 if '年' in df_complete.columns and '月数値' in df_complete.columns:
                     df_complete = df_complete.dropna(subset=['年', '月数値'])
                     df_complete['年月'] = pd.to_datetime(
                         df_complete['年'].astype(str) + '-' + df_complete['月数値'].astype(str) + '-01',
                         errors='coerce'
                     )
                     df_complete = df_complete.dropna(subset=['年月'])
                     df_complete = df_complete.drop(['月数値'], axis=1, errors='ignore')
                 else:
                     st.warning("年または月データの不足により、年月列は作成されませんでした。")

                 df_complete = df_complete.drop(['区分名'], axis=1, errors='ignore') # 区分名列を削除

            # 年コード削除
            df_complete = df_complete.drop(['年コード'], axis=1, errors='ignore')

            # データ型の最適化
            if '値（金額、数量）' in df_complete.columns:
                df_complete['値（金額、数量）'] = pd.to_numeric(df_complete['値（金額、数量）'], errors='coerce')
            if 'HSコード' in df_complete.columns:
                df_complete['HSコード'] = df_complete['HSコード'].astype(str)
            if '国コード' in df_complete.columns:
                df_complete['国コード'] = df_complete['国コード'].astype(str)
            if '税関コード' in df_complete.columns:
                df_complete['税関コード'] = df_complete['税関コード'].astype(str)
            if '年月' in df_complete.columns:
                # datetimeオブジェクトのままにして、CSV出力時にフォーマットする方が良い場合もある
                # df_complete['年月'] = pd.to_datetime(df_complete['年月']).dt.strftime('%Y-%m-%d')
                df_complete['年月'] = pd.to_datetime(df_complete['年月'])


            # 列の順序を整理 (存在する列のみ)
            final_cols_order = [
                'HSコード', '品目', '年', '月', '年月', '区分',
                '国コード', '国名', '税関コード', '税関',
                '値（金額、数量）', '単位'
            ]
            existing_final_cols = [col for col in final_cols_order if col in df_complete.columns]
            df_complete = df_complete[existing_final_cols]

        except Exception as e:
            import traceback
            st.error(f"データ整形中に予期せぬエラーが発生しました: {e}")
            st.code(traceback.format_exc())
            st.warning("整形前のデータを出力します。")
            # この時点でのdf_completeを使用

        # --- 結果表示とダウンロード ---
        st.success("処理が完了しました！")
        st.write(f"取得件数: {len(df_complete)}件 (処理成功: {processed_count}, スキップ: {skipped_count}, エラー: {error_count})")

        st.dataframe(df_complete)

        # ダウンロード用にCSVデータをメモリ上に作成 (cp932を試す)
        csv_data = None
        mime_type = 'text/csv'
        try:
            csv_buffer = io.BytesIO() # バイト列を扱うためにBytesIOを使用
            # encodingをcp932に変更し、エンコードできない文字は?に置換(errors='replace')
            df_complete.to_csv(csv_buffer, index=False, encoding='cp932', errors='replace', date_format='%Y-%m-%d')
            csv_data = csv_buffer.getvalue()
            st.info("CSVファイルは cp932 (Shift_JIS) エンコーディングで生成されます。")
        except Exception as e:
            st.error(f"CSVデータのエンコード中にエラーが発生しました (cp932): {e}")
            st.warning("cp932でのエンコードに失敗したため、UTF-8 (BOM付き)で再試行します。Excelで開く際に文字コードの指定が必要になる場合があります。")
            try:
                csv_buffer_utf8 = io.BytesIO()
                # フォールバックとしてUTF-8 (BOM付き) を使用
                df_complete.to_csv(csv_buffer_utf8, index=False, encoding='utf-8-sig', date_format='%Y-%m-%d')
                csv_data = csv_buffer_utf8.getvalue()
                mime_type = 'text/csv;charset=utf-8-sig' # MIMEタイプにcharset情報を追加
                st.info("CSVファイルは UTF-8 (BOM付き) エンコーディングで生成されます。")
            except Exception as e_utf8:
                st.error(f"CSVデータのエンコード中にエラーが発生しました (utf-8-sig): {e_utf8}")
                # ここで処理を停止するか、ダウンロードボタンを非表示にするなど
                csv_data = None # ダウンロードさせない

        # 3. ダウンロードボタン (データが正常に生成された場合のみ表示)
        if csv_data:
            current_time_str = datetime.now().strftime('%Y%m%d%H%M%S')
            download_filename = f"通関統計API_{selected_year}_{current_time_str}.csv"

            st.download_button(
                label="CSVファイルをダウンロード",
                data=csv_data, # エンコードされたバイト列を渡す
                file_name=download_filename,
                mime=mime_type, # 正しいMIMEタイプを指定
            )
        else:
            st.error("ダウンロード用CSVデータの生成に失敗しました。")

# スクリプトとして実行された場合はStreamlitを実行しないようにガード
# (ただし、このファイルはStreamlitアプリとして使うので通常不要)
# if __name__ == '__main__':
#    pass 