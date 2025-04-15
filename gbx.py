import io
from pygbx import Gbx
import logging


class Gbx2020(Gbx):
    def _read_node(self, class_id, depth, bp, add=True):
        try:
            return super()._read_node(class_id, depth, bp, add)
        except:
            return  # pygbx does not support tm2020, but I just need to read some metadata so just exiting the constructor works fine
        
    def get_at_seconds(self):
        try:
            return self.classes[2].times['author'] / 1000
        except:
            return -1

    def get_map_uid(self):
        try:
            return self.classes[-1].map_uid
        except:
            return ""

    def get_map_author_login(self):
        try:
            return self.classes[-1].map_author
        except:
            return ""

if __name__ == '__main__':
    logging.basicConfig(level=logging.CRITICAL)
    with open("test.Map.Gbx", 'rb') as f:
        data = Gbx2020(io.BytesIO(f.read()))
    print(f"Map UID: {data.get_map_uid()}\nMap Author login: {data.get_map_author_login()}\nAT: {data.get_at_seconds()}")