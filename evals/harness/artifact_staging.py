"""FD-rooted staging, identity, and bounded container-output import."""
from __future__ import annotations
import hashlib, json, os, stat, tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable
import workspace_lease

MAX_ENTRIES=10_000; MAX_DEPTH=32; MAX_FILE_BYTES=64*1024*1024
MAX_TOTAL_BYTES=512*1024*1024; MAX_PATH_BYTES=4096
MAX_ARCHIVE_STREAM_BYTES=MAX_TOTAL_BYTES+MAX_ENTRIES*(MAX_PATH_BYTES+2048)+10240
DEPENDENCY_ROOTS=frozenset({"node_modules","vendor","sandbox-cache"})
EXECUTION_CLOSURE_IGNORE=frozenset({".workspace-lease",".git",".wp-env","node_modules"})
SNAPSHOT_IGNORE=EXECUTION_CLOSURE_IGNORE

@dataclass(frozen=True)
class ManifestEntry:
    path:str; mode_class:str; size:int; sha256:str

@dataclass(frozen=True)
class StagedTree:
    lease:workspace_lease.WorkspaceLease; root:Path; manifest:tuple[ManifestEntry,...]

@dataclass
class SnapshotState:
    results:list; total:list[int]; seen:set[str]; folded:set[str]

@dataclass
class ArchiveState:
    intended:list[ManifestEntry]; total:int; registry:dict; members:set[str]; member_count:int=0

@dataclass(frozen=True)
class ArchiveVerification:
    manifest:tuple[ManifestEntry,...]; path_kinds:tuple[tuple[str,str],...]

class BoundedArchiveReader:
    def __init__(self,stream:BinaryIO,limit:int): self.stream=stream; self.limit=limit; self.total=0
    def read(self,size:int=-1):
        remaining=self.limit-self.total
        request=remaining+1 if size<0 else min(size,remaining+1)
        data=self.stream.read(request); self.total+=len(data)
        if self.total>self.limit: raise ValueError("archive stream exceeds transport bound")
        return data

def _require_fd_support():
    if not hasattr(os,"O_NOFOLLOW") or not hasattr(os,"O_DIRECTORY"): raise RuntimeError("descriptor-relative no-follow traversal is unavailable")

def open_directory_nofollow(path:Path)->int:
    _require_fd_support(); absolute=path.absolute()
    fd=os.open(absolute.anchor,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for component in absolute.parts[1:]:
            if component in {"",".",".."}: raise ValueError("unsafe path component")
            next_fd=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            if not stat.S_ISDIR(os.fstat(next_fd).st_mode): os.close(next_fd); raise ValueError("ancestor is not a directory")
            os.close(fd); fd=next_fd
        return fd
    except Exception: os.close(fd); raise

def _read_file(parent_fd:int,name:str,relative:Path,expected:os.stat_result,total:list[int])->tuple[bytes,os.stat_result]:
    if expected.st_nlink!=1: raise ValueError(f"artifact contains hardlink: {relative}")
    if expected.st_size>MAX_FILE_BYTES: raise ValueError("artifact file exceeds bounds")
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=parent_fd)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or (info.st_dev,info.st_ino)!=(expected.st_dev,expected.st_ino): raise ValueError(f"artifact changed while opening: {relative}")
        chunks=[]; size=0
        while chunk:=os.read(fd,min(65536,MAX_FILE_BYTES-size+1)):
            size+=len(chunk); total[0]+=len(chunk)
            if size>MAX_FILE_BYTES or total[0]>MAX_TOTAL_BYTES: raise ValueError("artifact exceeds bounds")
            chunks.append(chunk)
        after=os.fstat(fd)
        stable=lambda value:(value.st_dev,value.st_ino,stat.S_IFMT(value.st_mode),value.st_nlink,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
        if stable(after)!=stable(info): raise ValueError(f"artifact changed while reading: {relative}")
        return b"".join(chunks),after
    finally: os.close(fd)

def _walk_source_fd(fd:int,relative_dir:Path,policy:str,barrier,state:SnapshotState):
    if barrier: barrier(relative_dir)
    for name in sorted(os.listdir(fd)):
        if policy=="stage" and name in DEPENDENCY_ROOTS: raise ValueError(f"caller dependency root is forbidden: {name}")
        if policy=="post" and name in DEPENDENCY_ROOTS:
            info=os.stat(name,dir_fd=fd,follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode): raise ValueError("dependency root must be a real directory")
            continue
        if name in SNAPSHOT_IGNORE:
            if policy=="stage":
                info=os.stat(name,dir_fd=fd,follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode): raise ValueError("ignored root must be a real directory")
            continue
        relative=relative_dir/name; normalized=relative.as_posix(); folded=normalized.casefold()
        if len(relative.parts)>MAX_DEPTH: raise ValueError("artifact depth exceeds bounds")
        if normalized in state.seen or folded in state.folded: raise ValueError("duplicate or case-fold-colliding path")
        state.seen.add(normalized); state.folded.add(folded)
        if len(normalized.encode())>MAX_PATH_BYTES or len(state.seen)>MAX_ENTRIES: raise ValueError("artifact entry bounds exceeded")
        info=os.stat(name,dir_fd=fd,follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode): raise ValueError(f"artifact contains symlink: {relative}")
        if stat.S_ISDIR(info.st_mode):
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            try:
                opened=os.fstat(child)
                if (opened.st_dev,opened.st_ino)!=(info.st_dev,info.st_ino): raise ValueError("artifact directory changed while opening")
                _walk_source_fd(child,relative,policy,barrier,state)
            finally: os.close(child)
        elif stat.S_ISREG(info.st_mode):
            content,opened=_read_file(fd,name,relative,info,state.total); state.results.append((relative,content,opened))
        else: raise ValueError(f"artifact contains special file: {relative}")

def snapshot_regular_tree_with_kind(path:Path,*,dependency_policy:str="canonical",barrier:Callable[[Path],None]|None=None)->tuple[str,list[tuple[Path,bytes,os.stat_result]]]:
    _require_fd_support(); supplied=path.absolute(); state=SnapshotState([], [0], set(), set())
    if dependency_policy not in {"canonical","stage","post"}: raise ValueError("unknown dependency policy")
    if not supplied.name: raise ValueError("artifact root cannot be the filesystem root")
    parent=open_directory_nofollow(supplied.parent)
    try: before=os.stat(supplied.name,dir_fd=parent,follow_symlinks=False)
    except Exception: os.close(parent); raise
    if stat.S_ISLNK(before.st_mode): os.close(parent); raise ValueError(f"artifact root is a symlink: {path}")
    try:
        if stat.S_ISREG(before.st_mode):
            content,opened=_read_file(parent,supplied.name,Path(supplied.name),before,state.total); state.results.append((Path(supplied.name),content,opened)); kind="file"
        elif stat.S_ISDIR(before.st_mode):
            root=os.open(supplied.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
            try:
                if (os.fstat(root).st_dev,os.fstat(root).st_ino)!=(before.st_dev,before.st_ino): raise ValueError("artifact root changed while opening")
                _walk_source_fd(root,Path(),dependency_policy,barrier,state); kind="directory"
            finally: os.close(root)
        else: raise ValueError("artifact root is not regular")
    finally: os.close(parent)
    return kind,state.results

def snapshot_regular_tree(path:Path,*,dependency_policy:str="canonical"): return snapshot_regular_tree_with_kind(path,dependency_policy=dependency_policy)[1]

def digest_regular_tree(path:Path)->str:
    entries=[]
    for relative,content,info in snapshot_regular_tree(path): entries.append({"path":relative.as_posix(),"size":info.st_size,"sha256":hashlib.sha256(content).hexdigest()})
    lines="\n".join(json.dumps(item,ensure_ascii=True,separators=(",",":"),sort_keys=True) for item in entries)
    return hashlib.sha256(((lines+"\n") if lines else "").encode()).hexdigest()

def _write_all(fd:int,data:bytes):
    view=memoryview(data)
    while view:
        written=os.write(fd,view)
        if written<=0: raise OSError("short destination write")
        view=view[written:]

def _manifest_from_fd(root_fd:int,dependency_policy:str="post")->tuple[ManifestEntry,...]:
    results=[]; total=[0]
    def walk(fd,relative):
        for name in sorted(os.listdir(fd)):
            path=relative/name
            if len(path.parts)>MAX_DEPTH: raise ValueError("artifact depth exceeds bounds")
            info=os.stat(name,dir_fd=fd,follow_symlinks=False)
            if name in DEPENDENCY_ROOTS and dependency_policy=="post":
                if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode): raise ValueError("dependency root must be a real directory")
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                try: dependency_entries=os.listdir(child)
                finally: os.close(child)
                if dependency_entries: raise ValueError("dependency root must be empty after import")
                continue
            if stat.S_ISDIR(info.st_mode):
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                try: walk(child,path)
                finally: os.close(child)
            elif stat.S_ISREG(info.st_mode):
                content,opened=_read_file(fd,name,path,info,total)
                results.append(ManifestEntry(path.as_posix(),"executable" if stat.S_IMODE(opened.st_mode)&0o111 else "regular",len(content),hashlib.sha256(content).hexdigest()))
            else: raise ValueError("post-import tree contains special node")
    walk(root_fd,Path()); return tuple(results)

def _filesystem_kinds_from_fd(root_fd:int)->dict[str,str]:
    kinds={}
    def walk(fd,relative):
        for name in sorted(os.listdir(fd)):
            path=relative/name; info=os.stat(name,dir_fd=fd,follow_symlinks=False)
            kind="directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "other"
            kinds[path.as_posix()]=kind
            if kind=="directory":
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                try: walk(child,path)
                finally: os.close(child)
    walk(root_fd,Path()); return kinds

def _verified_lease_fd(lease:workspace_lease.WorkspaceLease)->int:
    fd=open_directory_nofollow(lease.root)
    try:
        root=os.fstat(fd)
        if not stat.S_ISDIR(root.st_mode) or stat.S_IMODE(root.st_mode)!=0o700 or (root.st_uid,root.st_gid)!=(os.getuid(),os.getgid()): raise ValueError("invalid workspace lease root")
        info=os.stat(".workspace-lease",dir_fd=fd,follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1 or (info.st_uid,info.st_gid)!=(os.getuid(),os.getgid()): raise ValueError("invalid workspace lease sentinel")
        sentinel=os.open(".workspace-lease",os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        try: payload=os.read(sentinel,256).decode()
        finally: os.close(sentinel)
        if payload!=f"{lease.lease_id}\n{lease.purpose.value}\n": raise ValueError("workspace lease sentinel mismatch")
        return fd
    except Exception: os.close(fd); raise

def _write_snapshot(snapshot,root_fd:int):
    try:
        for relative,content,info in snapshot:
            fd=root_fd
            opened=[]
            try:
                for part in relative.parts[:-1]:
                    try: child=workspace_lease.create_secure_directory(fd,part)
                    except FileExistsError: child=workspace_lease.open_secure_directory(fd,part)
                    opened.append(child); fd=child
                normalized_mode=0o700 if stat.S_IMODE(info.st_mode)&0o111 else 0o600
                out=workspace_lease.create_secure_file(fd,relative.name,normalized_mode)
                try: _write_all(out,content)
                finally: os.close(out)
            finally:
                for child in reversed(opened): os.close(child)
    finally: pass

def _create_artifact_root(lease_fd:int)->int:
    try: return workspace_lease.create_secure_directory(lease_fd,"artifact")
    except RuntimeError as exc: raise ValueError("staged destination root changed") from exc

def stage_tree(source:Path,parent:Path|None=None)->StagedTree:
    kind,snapshot=snapshot_regular_tree_with_kind(source,dependency_policy="stage")
    lease=workspace_lease.create_ephemeral(parent,workspace_lease.WorkspacePurpose.ARTIFACT_EXECUTION)
    try:
        lease_fd=_verified_lease_fd(lease); root_fd=_create_artifact_root(lease_fd); root=lease.root/"artifact"
        _write_snapshot(snapshot,root_fd)
        intended=tuple(ManifestEntry(p.as_posix(),"executable" if stat.S_IMODE(i.st_mode)&0o111 else "regular",len(c),hashlib.sha256(c).hexdigest()) for p,c,i in snapshot)
        manifest=_manifest_from_fd(root_fd,"canonical")
        if manifest!=intended: raise ValueError("staged manifest mismatch")
        intended_kinds={}
        for path,_content,_info in snapshot:
            for index in range(1,len(path.parts)): intended_kinds[Path(*path.parts[:index]).as_posix()]="directory"
            intended_kinds[path.as_posix()]="file"
        if _filesystem_kinds_from_fd(root_fd)!=intended_kinds: raise ValueError("staged filesystem entry mismatch")
        current=os.stat("artifact",dir_fd=lease_fd,follow_symlinks=False); opened=os.fstat(root_fd)
        if (current.st_dev,current.st_ino)!=(opened.st_dev,opened.st_ino): raise ValueError("staged destination root changed")
        os.close(root_fd); os.close(lease_fd)
        return StagedTree(lease,root,manifest)
    except Exception:
        for name in ("root_fd","lease_fd"):
            if name in locals():
                try: os.close(locals()[name])
                except OSError: pass
        workspace_lease.cleanup(lease); raise

def _destination_parent(root_fd:int,parts:tuple[str,...])->tuple[int,list[int]]:
    fd=root_fd; opened=[]
    for part in parts:
        try: child=workspace_lease.create_secure_directory(fd,part)
        except FileExistsError: child=workspace_lease.open_secure_directory(fd,part)
        opened.append(child); fd=child
    return fd,opened

def _validate_archive_member(member,state:ArchiveState):
    state.member_count+=1; path=PurePosixPath(member.name)
    if str(path)=="." and not path.parts:
        if state.member_count>MAX_ENTRIES: raise ValueError("archive bounds exceeded")
        if "." in state.members: raise ValueError("duplicate archive member")
        state.members.add(".")
        if not member.isdir(): raise ValueError("archive root member must be a directory")
        return None
    if path.is_absolute() or any(part in {"",".",".."} for part in path.parts): raise ValueError("unsafe archive path")
    normalized=path.as_posix()
    if state.member_count>MAX_ENTRIES or len(path.parts)>MAX_DEPTH or len(normalized.encode())>MAX_PATH_BYTES: raise ValueError("archive bounds exceeded")
    if normalized in state.members: raise ValueError("duplicate archive member")
    state.members.add(normalized)
    kind="directory" if member.isdir() else "file" if member.isfile() and not member.islnk() and not member.issym() else "other"
    return path,normalized,kind

def _register_archive_prefixes(path,kind,state:ArchiveState):
    for index in range(1,len(path.parts)+1):
        prefix=PurePosixPath(*path.parts[:index]).as_posix(); folded=prefix.casefold(); prefix_kind=kind if index==len(path.parts) else "directory"
        existing=state.registry.get(folded)
        if existing and (existing[0]!=prefix or existing[1]!=prefix_kind): raise ValueError("archive prefix alias or kind conflict")
        state.registry[folded]=(prefix,prefix_kind)
        if len(state.registry)>MAX_ENTRIES: raise ValueError("archive prefix bounds exceeded")

def _prepare_archive_target(path,kind,dependency,root_fd,state):
    if dependency:
        root_kind=state.registry[path.parts[0].casefold()][1]
        if len(path.parts)==1 and kind!="directory": raise ValueError("dependency archive root must be a directory")
        if root_kind!="directory": raise ValueError("dependency archive root kind conflict")
        _parent,opened=_destination_parent(root_fd,(path.parts[0],))
        for fd in reversed(opened): os.close(fd)
        return False
    if kind=="directory":
        _parent,opened=_destination_parent(root_fd,path.parts)
        for fd in reversed(opened): os.close(fd)
        return False
    if kind=="other": raise ValueError("archive contains link or special node")
    return True

def _consume_archive_payload(archive,member,path,normalized,materialize,root_fd,state):
    if not member.isfile(): return
    if member.size>MAX_FILE_BYTES: raise ValueError("archive file exceeds bounds")
    state.total+=member.size
    if state.total>MAX_TOTAL_BYTES: raise ValueError("archive exceeds bounds")
    source=archive.extractfile(member)
    if source is None: raise ValueError("archive file is unreadable")
    opened=[]; out_fd=None; mode_class="executable" if member.mode&0o111 else "regular"
    if materialize:
        parent_fd,opened=_destination_parent(root_fd,path.parts[:-1])
        out_fd=workspace_lease.create_secure_file(parent_fd,path.name,0o700 if mode_class=="executable" else 0o600)
    digest=hashlib.sha256(); written=0
    try:
        while chunk:=source.read(min(65536,member.size-written+1)):
            written+=len(chunk)
            if written>member.size or written>MAX_FILE_BYTES: raise ValueError("archive size mismatch")
            if out_fd is not None: _write_all(out_fd,chunk)
            digest.update(chunk)
    finally:
        if out_fd is not None: os.close(out_fd)
        for fd in reversed(opened): os.close(fd)
    if written!=member.size: raise ValueError("archive size mismatch")
    if materialize: state.intended.append(ManifestEntry(normalized,mode_class,written,digest.hexdigest()))

def _verify_archive_payload(archive,member,path,normalized,state):
    if not member.isfile(): return
    if member.size>MAX_FILE_BYTES: raise ValueError("archive file exceeds bounds")
    state.total+=member.size
    if state.total>MAX_TOTAL_BYTES: raise ValueError("archive exceeds bounds")
    source=archive.extractfile(member)
    if source is None: raise ValueError("archive file is unreadable")
    digest=hashlib.sha256(); written=0
    while chunk:=source.read(min(65536,member.size-written+1)):
        written+=len(chunk)
        if written>member.size: raise ValueError("archive size mismatch")
        digest.update(chunk)
    if written!=member.size: raise ValueError("archive size mismatch")
    mode="executable" if member.mode&0o111 else "regular"
    state.intended.append(ManifestEntry(normalized,mode,written,digest.hexdigest()))

def verify_tar_stream_manifest(stream:BinaryIO)->ArchiveVerification:
    state=ArchiveState([],0,{},set()); bounded=BoundedArchiveReader(stream,MAX_ARCHIVE_STREAM_BYTES)
    with tarfile.open(fileobj=bounded,mode="r|") as archive:
        for member in archive:
            validated=_validate_archive_member(member,state)
            if validated is None: continue
            path,normalized,kind=validated; _register_archive_prefixes(path,kind,state)
            if path.parts[0] in DEPENDENCY_ROOTS: raise ValueError("dependency archive path forbidden in strict mode")
            if kind=="other": raise ValueError("archive contains link or special node")
            _verify_archive_payload(archive,member,path,normalized,state)
    manifest=tuple(sorted(state.intended,key=lambda item:item.path))
    kinds=tuple(sorted((path,kind) for path,kind in state.registry.values()))
    return ArchiveVerification(manifest,kinds)

def _finalize_archive(root_fd,lease_fd,state):
    manifest=_manifest_from_fd(root_fd,"post")
    if manifest!=tuple(sorted(state.intended,key=lambda item:item.path)): raise ValueError("imported manifest mismatch")
    intended_kinds={}
    for _folded,(path,kind) in state.registry.items():
        parts=PurePosixPath(path).parts
        if parts[0] in DEPENDENCY_ROOTS:
            if len(parts)==1: intended_kinds[path]="directory"
        else: intended_kinds[path]=kind
    if _filesystem_kinds_from_fd(root_fd)!=intended_kinds: raise ValueError("imported filesystem entry mismatch")
    current=os.stat("artifact",dir_fd=lease_fd,follow_symlinks=False); opened=os.fstat(root_fd)
    if (current.st_dev,current.st_ino)!=(opened.st_dev,opened.st_ino): raise ValueError("import destination root changed")
    return manifest

def import_tar_stream(stream:BinaryIO,parent:Path|None=None,*,dependency_policy:str="post")->StagedTree:
    lease=workspace_lease.create_ephemeral(parent,workspace_lease.WorkspacePurpose.ARTIFACT_EXECUTION)
    state=ArchiveState([],0,{},set())
    try:
        if dependency_policy not in {"post","strict"}: raise ValueError("unknown archive dependency policy")
        lease_fd=_verified_lease_fd(lease); root_fd=_create_artifact_root(lease_fd); root=lease.root/"artifact"
        bounded=BoundedArchiveReader(stream,MAX_ARCHIVE_STREAM_BYTES)
        with tarfile.open(fileobj=bounded,mode="r|") as archive:
            for member in archive:
                validated=_validate_archive_member(member,state)
                if validated is None: continue
                path,normalized,kind=validated; _register_archive_prefixes(path,kind,state)
                dependency=path.parts[0] in DEPENDENCY_ROOTS
                if dependency and dependency_policy=="strict": raise ValueError("dependency archive path forbidden in strict mode")
                materialize=_prepare_archive_target(path,kind,dependency,root_fd,state)
                _consume_archive_payload(archive,member,path,normalized,materialize,root_fd,state)
        manifest=_finalize_archive(root_fd,lease_fd,state)
        os.close(root_fd); os.close(lease_fd)
        return StagedTree(lease,root,manifest)
    except Exception:
        for name in ("root_fd","lease_fd"):
            if name in locals():
                try: os.close(locals()[name])
                except OSError: pass
        workspace_lease.cleanup(lease); raise
