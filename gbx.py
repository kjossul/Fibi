from pygbx import Gbx

class Gbx2020(Gbx):
    def _read_node(self, class_id, depth, bp, add=True):
        try:
            return super()._read_node(class_id, depth, bp, add)
        except:
            return  # pygbx does not support tm2020, but I just need to read AT time which still works
        
    def get_at_seconds(self):
        try:
            return round(self.classes[2].times['author'] / 1000)
        except:
            return -1
