"""Local, display-only university/team identities; no referee/control authority.

The official engine's match_info JSON supplies red_team/blue_team with name,
college_name, emblem and college_logo. Import is explicit, local and bounded;
remote URLs are never fetched, and painting never reads files or decodes PNGs.
"""
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QImageReader

LOG = logging.getLogger(__name__)
SIDES = ('Red', 'Blue')


def _label(value):
    if not isinstance(value, str):
        raise ValueError('School/team names must be text')
    value = value.strip()
    if len(value) > 80 or any(ord(c) < 32 or c in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069' for c in value):
        raise ValueError('School/team name is too long or contains control characters')
    return value


def _json(path):
    if path.stat().st_size > 256*1024:
        raise ValueError('Oversized match metadata')
    data = path.read_bytes()
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            value = json.loads(data.decode(encoding))
            if not isinstance(value, dict):
                raise ValueError('Expected a match metadata object')
            return value
        except (UnicodeError, json.JSONDecodeError):
            continue
    raise ValueError('Invalid UTF-8/GB18030 match JSON')


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)  # Exact mkstemp file only, never recursive.


@dataclass(frozen=True)
class TeamIdentity:
    school: str = ''
    team: str = ''
    logo: str = ''

    def validated(self):
        if not isinstance(self.logo,str) or (self.logo and not re.fullmatch(r'[a-f0-9]{64}\.png', self.logo)):
            raise ValueError('Unsafe team logo id')
        return TeamIdentity(_label(self.school), _label(self.team), self.logo)


@dataclass(frozen=True)
class TeamVisual:
    identity: TeamIdentity
    image: QImage

    @property
    def cache_key(self):
        return self.identity, self.image.cacheKey()

    @property
    def tooltip(self):
        return ' · '.join(x for x in (self.identity.school, self.identity.team) if x)


class MatchTeamStore:
    def __init__(self, root: Path | None = None):
        self.root = root
        self.teams = {side: TeamIdentity() for side in SIDES}
        self.visuals = {side: TeamVisual(self.teams[side], QImage()) for side in SIDES}
        self.error = ''
        if root is not None and (root/'teams.json').is_file():
            try:
                data = _json(root/'teams.json')
                if data.get('schema') != 1:
                    raise ValueError('Unknown match-team schema')
                teams = {side: TeamIdentity(**data['teams'][side]).validated() for side in SIDES}
                self._activate(teams)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self.error = str(exc)
                LOG.warning('Match team identities unavailable: %s', exc)

    def _image(self, name):
        if not name or self.root is None:
            return QImage()
        path = self.root/'logos'/name
        if not path.resolve().is_relative_to(self.root.resolve()) or path.stat().st_size > 8*1024*1024:
            raise ValueError('Invalid team logo path/size')
        data = path.read_bytes()
        if len(data) > 8*1024*1024 or hashlib.sha256(data).hexdigest()+'.png' != name:
            raise ValueError('Invalid team logo checksum')
        reader = QImageReader(str(path))
        size = reader.size()
        if not size.isValid() or max(size.width(), size.height()) > 512:
            raise ValueError('Invalid normalized logo dimensions')
        image = reader.read()
        if image.isNull():
            raise ValueError('Team logo cannot be decoded')
        return image.convertToFormat(QImage.Format_ARGB32_Premultiplied)

    def _activate(self, teams):
        visuals = {side: TeamVisual(team, self._image(team.logo)) for side,team in teams.items()}
        self.teams, self.visuals = teams, visuals
        self.error = ''

    def save(self, teams):
        checked = {side: teams[side].validated() for side in SIDES}
        visuals = {side: TeamVisual(team, self._image(team.logo)) for side,team in checked.items()}
        if self.root is not None:
            data = {'schema': 1, 'scope': 'local-display-only',
                    'teams': {side: vars(team) for side,team in checked.items()}}
            _atomic(self.root/'teams.json', (json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        self.teams, self.visuals, self.error = checked, visuals, ''

    def import_logo(self, path):
        if self.root is None:
            raise ValueError('A writable local identity directory is required')
        path = Path(path)
        if path.stat().st_size > 8*1024*1024:
            raise ValueError('Logo must be smaller than 8 MiB')
        reader = QImageReader(str(path)); reader.setAutoTransform(True)
        size = reader.size()
        if (bytes(reader.format()).lower() not in (b'png', b'jpeg', b'webp')
                or not size.isValid() or size.width()*size.height() > 4_194_304):
            raise ValueError('Use a PNG/JPEG/WebP logo with at most 4 megapixels')
        image = reader.read()
        if image.isNull():
            raise ValueError('Logo cannot be decoded')
        if max(image.width(), image.height()) > 512:
            image = image.scaled(512,512,Qt.KeepAspectRatio,Qt.SmoothTransformation)
        output = QBuffer(); output.open(QIODevice.WriteOnly)
        if not image.save(output,'PNG'):
            raise ValueError('Logo cannot be normalized')
        data = bytes(output.data()); name = hashlib.sha256(data).hexdigest()+'.png'
        _atomic(self.root/'logos'/name, data)
        return name

    def read_official(self, path):
        """Explicit adapter for the inspected official engine schema, not MQTT."""
        path = Path(path); data = _json(path); teams = {}
        for side in SIDES:
            item = data.get(side.lower()+'_team')
            if not isinstance(item, dict):
                raise ValueError('Expected official red_team and blue_team objects')
            school = item.get('college_name') or ''
            team = item.get('name') or ''
            school = _label(school); team = _label(team)
            logo = ''
            # The engine caches the actual match logos beside match_info JSON.
            candidates = [path.parent/f'compress_{side.lower()}_team_logo.png']
            reference = item.get('college_logo') or item.get('emblem') or ''
            if isinstance(reference,str) and reference and Path(reference).name == reference and not re.search(r'[:/\\]',reference):
                candidates.append(path.parent/reference)
            for candidate in candidates:
                if candidate.is_file():
                    logo = self.import_logo(candidate)
                    break
            teams[side] = TeamIdentity(school,team,logo)
        return teams
