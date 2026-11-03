"""Offline FanGraphs import contract tests using synthetic fixtures."""
import csv
import json
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
import pytest
from baseball_run_engine.blend import blend_files
from baseball_run_engine.cli import main
from baseball_run_engine.events import Event
from baseball_run_engine.fangraphs import (
    ProjectionDownloadError,extract_records,fetch_json,normalize_records,
    normalize_projection_row,projection_url,read_export_csv,save_snapshot)
from baseball_run_engine.projections import read_projection_csv

FIXTURE=Path(__file__).parent/'fixtures'/'fangraphs_export_sample.csv'

def test_csv_and_aliases():
    normalized,summary=normalize_records(read_export_csv(FIXTURE),'zips')
    assert len(normalized)==2
    assert summary['included']==2
    assert normalized[0]['FGID']=='101'
    assert normalized[0]['H']=='130.0'

def test_api_x1b_fields():
    rec={'playerName':'Sample Player','playerid':123,'pa':500,'x1b':76,
         'x2b':25,'x3b':2,'hr':27,'bb':45,'so':110,'hbp':5}
    n=normalize_projection_row(rec,'steamer')
    assert float(n['H'])==130
    assert n['FGID']=='123'
    assert len(extract_records({'data':[rec]}))==1

def test_url():
    url=projection_url('zips')
    assert 'type=zips' in url and 'stats=bat' in url and 'players=0' in url
    with pytest.raises(ValueError): projection_url('invalid')

def test_snapshot(tmp_path):
    report=save_snapshot('steamer',tmp_path,payload=read_export_csv(FIXTURE),
                         source='CSV export: local.csv',
                         timestamp=datetime(2026,11,2,tzinfo=timezone.utc))
    players=read_projection_csv(report['csv'])
    assert len(players)==2
    assert players[0].probability(Event.HR)==pytest.approx(.04)
    manifest=json.loads(Path(report['manifest']).read_text())
    assert manifest['system']=='steamer'

def test_schema_rejection():
    row=dict(read_export_csv(FIXTURE)[0]); row.pop('SO')
    with pytest.raises(ValueError,match='validation failed'):
        normalize_records([row],'zips')
    with pytest.raises(ValueError,match='schema'):
        extract_records({'error':'forbidden'})

def test_blend_rates(tmp_path):
    a=read_export_csv(FIXTURE)
    left=tmp_path/'steamer.csv'; right=tmp_path/'zips.csv'
    for path,rows in ((left,a),(right,[dict(r) for r in a])):
        if path==right:
            rows[0]['PA']='600'; rows[0]['HR']='12'
            rows[0]['H']='120'; rows[0]['SO']='126'
        with path.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=rows[0].keys())
            writer.writeheader(); writer.writerows(rows)
    dest=tmp_path/'blend.csv'
    stats=blend_files(left,right,dest)
    assert stats['matched']==2
    joined={r['FGID']:r for r in read_export_csv(dest)}
    assert float(joined['101']['HR'])==pytest.approx(16.5)
    assert read_projection_csv(dest)[0].probability(Event.HR)==pytest.approx(.03)

def test_403():
    with patch('baseball_run_engine.fangraphs.urlopen') as mock:
        mock.side_effect=HTTPError('https://www.fangraphs.com/api/projections',403,'Forbidden',{},None)
        with pytest.raises(ProjectionDownloadError,match='403'):
            fetch_json('steamer')

def test_cli_import(tmp_path,capsys):
    main(['fetch-projections','--system','zips','--csv',str(FIXTURE),
          '--out-dir',str(tmp_path)])
    res=json.loads(capsys.readouterr().out)
    assert res[0]['included']==2
    assert len(read_projection_csv(res[0]['csv']))==2
