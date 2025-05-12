from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os
import logging # Логирование қосылды

# Google Drive папкасының ID-сын осында қойыңыз. Қауіпсіздік үшін оны қоршаған орта айнымалысынан алған дұрыс.
FOLDER_ID = '1ETI_E2HE-CH709nYiMreE5C_VUOeg20V' # Нақты ID-мен ауыстырыңыз
SERVICE_ACCOUNT_FILE = 'credentials.json' # Сервистік тіркелгі файлының жолы

# Google Drive-қа жүктеу функциясы
def upload_to_drive(file_path, file_name):
    """Файлды Google Drive-қа жүктейді және файлдың ID-сын қайтарады."""
    SCOPES = ['https://www.googleapis.com/auth/drive']

    # Файлдардың бар-жоғын тексеру
    if not os.path.exists(file_path):
        logging.error(f"Жүктеу үшін файл табылмады: {file_path}")
        raise FileNotFoundError(f"Файл табылмады: {file_path}")
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
         logging.error(f"Service account файлы табылмады: {SERVICE_ACCOUNT_FILE}")
         raise FileNotFoundError(f"Service account файлы табылмады: {SERVICE_ACCOUNT_FILE}")

    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build('drive', 'v3', credentials=credentials)

        file_metadata = {'name': file_name, 'parents': [FOLDER_ID]}
        media = MediaFileUpload(file_path, resumable=True)

        # Файлды жүктеу
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        file_id = file.get('id')
        logging.info(f"Файл '{file_name}' Google Drive-қа сәтті жүктелді, ID: {file_id}")

        # (Міндетті емес) Файлға рұқсаттарды орнату. Мысалы, барлығына оқу рұқсатын беру:
        # try:
        #     permission = {'type': 'anyone', 'role': 'reader'}
        #     service.permissions().create(fileId=file_id, body=permission).execute()
        #     logging.info(f"'{file_name}' файлына жалпыға ортақ оқу рұқсаты берілді.")
        # except Exception as perm_e:
        #     logging.error(f"Файл рұқсаттарын орнату кезінде қате: {perm_e}")
        #     # Рұқсат орнату қатесі жүктеудің сәтті болғанын жоққа шығармайды

        return file_id # Файлдың ID-сын қайтару

    except Exception as e:
        logging.exception(f"Google Drive-қа '{file_name}' файлын жүктеу кезінде қате орын алды:")
        raise e # Қатені жоғары деңгейге жіберу (main.py оны ұстай алады)

# --- Aiogram хабарлама өңдеушілері осы файлдан алынып тасталды ---
# Бұл файл тек Google Drive-қа жүктеу логикасын қамтиды.
# Telegram хабарламаларын өңдеу main.py файлында жүзеге асырылады.
