# stapel-profiles

[![CI](https://img.shields.io/github/actions/workflow/status/usestapel/stapel-profiles/ci.yml?branch=main&logo=github&label=CI)](https://github.com/usestapel/stapel-profiles/actions/workflows/ci.yml?query=branch%3Amain)
[![coverage](https://img.shields.io/codecov/c/github/usestapel/stapel-profiles?branch=main&logo=codecov&label=coverage)](https://app.codecov.io/gh/usestapel/stapel-profiles)
[![pypi](https://img.shields.io/pypi/v/stapel-profiles?logo=pypi&logoColor=white&label=pypi)](https://pypi.org/project/stapel-profiles/)
[![downloads](https://static.pepy.tech/badge/stapel-profiles/month)](https://pepy.tech/project/stapel-profiles)
[![python](https://img.shields.io/pypi/pyversions/stapel-profiles?logo=python&logoColor=white)](https://pypi.org/project/stapel-profiles/)
[![license](https://img.shields.io/github/license/usestapel/stapel-profiles)](https://github.com/usestapel/stapel-profiles/blob/main/LICENSE)

> User profiles — avatars, social graph (follow/block), privacy settings, language preferences

Part of the [Stapel framework](https://github.com/usestapel) — composable Django apps for building production-grade platforms.

**Error reference:** [Errors (EN)](docs/errors.en.md) · [Ошибки (RU)](docs/errors.ru.md)

## Installation

```bash
pip install stapel-profiles
```

## Quick start

```python
# settings.py
INSTALLED_APPS = [
    ...
    'stapel_profiles',
]
```

## Bus events

### Emits
| `profile.updated` | [schema](schemas/emits/profile.updated.json) | User profile fields were updated. |

### Consumes
| `user.deleted` | [schema](schemas/consumes/user.deleted.json) |
| `user.deletion_initiated` | [schema](schemas/consumes/user.deletion_initiated.json) |

## License

MIT — see [LICENSE](LICENSE)
