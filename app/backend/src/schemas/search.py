from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SearchPlan:
    keyword: str = ""
    region: str = ""
    skills: tuple[str, ...] = ()
    limit: int = 5

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or set(value) - {"keyword", "region", "skills", "limit"}:
            raise ValueError("Invalid search fields")
        keyword, region = value.get("keyword", ""), value.get("region", "")
        skills, limit = value.get("skills", []), value.get("limit", 5)
        if not isinstance(keyword, str) or len(keyword) > 120:
            raise ValueError("Invalid keyword")
        if not isinstance(region, str) or len(region) > 80:
            raise ValueError("Invalid region")
        if (not isinstance(skills, list) or len(skills) > 10 or
                any(not isinstance(s, str) or not s.strip() or len(s) > 80 for s in skills)):
            raise ValueError("Invalid skills")
        if type(limit) is not int or not 1 <= limit <= 30:
            raise ValueError("Invalid limit")
        return cls(keyword.strip(), region.strip(), tuple(dict.fromkeys(skills)), limit)

    def to_dict(self):
        return asdict(self)
