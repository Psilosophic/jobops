"""Register a resume file with a track (creates an immutable new version).

Usage (inside the api container, file mounted/copied into /srv/jobops/exports):
    python -m app.profile.load_resume iam "/srv/jobops/exports/resumes/Scott Shelton Resume - IAM (ATS).docx"
"""
import hashlib
import shutil
import sys
from pathlib import Path

from sqlmodel import Session, select

from app.db import engine
from app.models.profile import Resume, ResumeTrack, ResumeVersion

RESUME_DIR = Path("/srv/jobops/exports/resumes")


def load(track_slug: str, file_path: str) -> dict:
    src = Path(file_path)
    if not src.exists():
        raise SystemExit(f"file not found: {src}")
    with Session(engine) as s:
        track = s.exec(select(ResumeTrack).where(ResumeTrack.slug == track_slug)).first()
        if track is None:
            raise SystemExit(f"unknown track: {track_slug}")
        resume = s.exec(select(Resume).where(Resume.track_id == track.id)).first()
        if resume is None:
            resume = Resume(track_id=track.id, name=f"{track.name} resume")
            s.add(resume)
            s.commit()
            s.refresh(resume)
        last = s.exec(
            select(ResumeVersion).where(ResumeVersion.resume_id == resume.id)
            .order_by(ResumeVersion.version_no.desc())
        ).first()
        version_no = (last.version_no + 1) if last else 1
        RESUME_DIR.mkdir(parents=True, exist_ok=True)
        # Neutral, versioned filename — never leaks another employer's name.
        dest = RESUME_DIR / f"{track_slug}_v{version_no}{src.suffix}"
        shutil.copy2(src, dest)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if last and last.content_hash == digest:
            return {"skipped": "identical to latest version", "version": last.version_no}
        s.add(ResumeVersion(resume_id=resume.id, version_no=version_no,
                            file_path=str(dest), content_hash=digest))
        s.commit()
        return {"track": track_slug, "version": version_no, "path": str(dest)}


if __name__ == "__main__":
    print(load(sys.argv[1], sys.argv[2]))
