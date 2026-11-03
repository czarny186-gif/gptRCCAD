"""Zapisuje numer i datę kompilacji (CI uruchamia to przed testami i budową), żeby okno „O programie” pokazywało dokładną wersję."""
import datetime
import os
import pathlib

number = int(os.environ.get('GITHUB_RUN_NUMBER', '0') or 0)
pathlib.Path(__file__).with_name('rccad').joinpath('_build.py').write_text(
    f"BUILD = {number}\nBUILD_DATE = {datetime.date.today().isoformat()!r}\n", encoding='utf-8')
