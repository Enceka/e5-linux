"""Validated GPT gap operations, shared with the existing MU300 installer."""
import struct
import uuid
import zlib

def gpt_backup_layout(primary, backup, sectors):
    def header(raw,at):
        if len(raw)!=512 or raw[:8]!=b'EFI PART':raise ValueError('Invalid GPT header')
        size=struct.unpack_from('<I',raw,12)[0]
        if not 92<=size<=512:raise ValueError('Invalid GPT header size')
        check=bytearray(raw[:size]);expected=struct.unpack_from('<I',check,16)[0];check[16:20]=bytes(4)
        if zlib.crc32(check)!=expected:raise ValueError('GPT header checksum failed')
        current,alternate=struct.unpack_from('<QQ',raw,24)
        table,count,entrysize=struct.unpack_from('<QII',raw,72)
        if current!=at or count<1 or count>1024 or entrysize!=128:raise ValueError('Unsupported GPT geometry')
        return alternate,table,(count*entrysize+511)//512,raw[56:72],raw[80:92]
    a=header(primary,1);b=header(backup,sectors-1)
    if a[0]!=sectors-1 or b[0]!=1 or a[3:]!=b[3:]:raise ValueError('GPT copies disagree')
    front=a[1]+a[2];tail=b[1]
    if not (2<=a[1]<front<=4096 and sectors-4096<=tail and tail+b[2]==sectors-1):raise ValueError('GPT backup range is invalid')
    return front,tail

def gpt_space(first,last,sectors):
    """Validate both on-disk GPT copies and return aligned, genuinely unallocated ranges."""
    primary=first[512:1024];backup=last[-512:]
    front,tail=gpt_backup_layout(primary,backup,sectors)
    if len(first)!=front*512 or len(last)!=(sectors-tail)*512:
        raise ValueError('Incomplete GPT snapshot')
    start,end=struct.unpack_from('<QQ',primary,40)
    if (start,end)!=struct.unpack_from('<QQ',backup,40) or not front<=start<=end<tail:
        raise ValueError('GPT usable bounds disagree or overlap metadata')
    table,count,entry=struct.unpack_from('<QII',primary,72)
    data=first[table*512:table*512+count*entry]
    if data!=last[:count*entry] or zlib.crc32(data)!=struct.unpack_from('<I',primary,88)[0]:
        raise ValueError('GPT table checksum/copy mismatch')
    parts=[];empty=[]
    for i in range(count):
        raw=data[i*entry:(i+1)*entry]
        if raw[:16]==bytes(16):empty.append(i);continue
        a,b=struct.unpack_from('<QQ',raw,32)
        name=raw[56:128].decode('utf-16-le').split('\0',1)[0]
        if not start<=a<=b<=end:raise ValueError('GPT partition outside usable bounds: '+name)
        parts.append({'n':i+1,'start':a,'end':b,'name':name})
    at=start;gaps=[]
    for part in sorted(parts,key=lambda p:p['start'])+[{'start':end+1,'end':end}]:
        if part['start']<at:raise ValueError('Overlapping GPT partitions')
        aligned=(at+2047)//2048*2048
        limit=(part['start']//2048)*2048
        if limit>aligned:gaps.append((aligned,limit-aligned))
        at=part['end']+1
    return {'front':front,'tail':tail,'parts':parts,'empty':empty,'gaps':gaps,
            'largest':max((size for _,size in gaps),default=0) if empty else 0}

def gpt_add_root(first,last,sectors,offset,need,root_name="mu300root"):
    info=gpt_space(first,last,sectors)
    if any(p['name']==root_name for p in info['parts']):raise ValueError('mu300root already exists')
    if not info['empty'] or need<4194304 or offset%2048 or need%2048 or not any(
            offset>=a and offset+need<=a+n for a,n in info['gaps']):
        raise ValueError('Requested root is not in an aligned GPT free range')
    idx=info['empty'][0];entry=bytearray(128)
    entry[:16]=uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4').bytes_le
    entry[16:32]=uuid.uuid4().bytes_le
    struct.pack_into('<QQ',entry,32,offset,offset+need-1)
    name=root_name.encode('utf-16-le');entry[56:56+len(name)]=name
    copies=[]
    for raw,header_offset,table_offset in ((first,512,struct.unpack_from('<Q',first,584)[0]*512),(last,len(last)-512,0)):
        new=bytearray(raw);new[table_offset+idx*128:table_offset+(idx+1)*128]=entry
        count=struct.unpack_from('<I',new,header_offset+80)[0]
        struct.pack_into('<I',new,header_offset+88,zlib.crc32(new[table_offset:table_offset+count*128]))
        struct.pack_into('<I',new,header_offset+16,0)
        hsize=struct.unpack_from('<I',new,header_offset+12)[0]
        struct.pack_into('<I',new,header_offset+16,zlib.crc32(new[header_offset:header_offset+hsize]))
        copies.append(bytes(new))
    gpt_space(*copies,sectors)
    return copies

def free_root_range(info,need):
    if not info['empty']:return None
    # Old MU300 installs may live outside GPT at this fixed raw offset. Such
    # an area is retained even though a partition table calls it unallocated.
    gaps=info.get('safe_gaps',info['gaps'])
    candidates=[(n,a) for a,n in gaps if n>=need]
    return max(candidates)[1] if candidates else None

