import sys,json,time
sys.path.insert(0,chr(39)+chr(47)+chr(85)+chr(115)+chr(101)+chr(114)+chr(115)+chr(47)+chr(97)+chr(108)+chr(105)+chr(99)+chr(101)+chr(47)+chr(72)+chr(97)+chr(110)+chr(100)+chr(39))
from hand.perception.cdp_core import list_pages, cdp_connect, cdp_call
from hand.router import route_open, route_do
pages=list_pages()
ws=cdp_connect(pages[0][chr(39)+chr(119)+chr(101)+chr(98)+chr(83)+chr(111)+chr(99)+chr(107)+chr(101)+chr(116)+chr(68)+chr(101)+chr(98)+chr(117)+chr(103)+chr(103)+chr(101)+chr(114)+chr(85)+chr(114)+chr(108)+chr(39)])
cdp_call(ws,chr(39)+chr(80)+chr(97)+chr(103)+chr(101)+chr(46)+chr(101)+chr(110)+chr(97)+chr(98)+chr(108)+chr(101)+chr(39))
cdp_call(ws,chr(39)+chr(80)+chr(97)+chr(103)+chr(101)+chr(46)+chr(110)+chr(97)+chr(118)+chr(105)+chr(103)+chr(97)+chr(116)+chr(101)+chr(39),{chr(39)+chr(117)+chr(114)+chr(108)+chr(39):chr(39)+chr(104)+chr(116)+chr(116)+chr(112)+chr(115)+chr(58)+chr(47)+chr(47)+chr(101)+chr(120)+chr(97)+chr(109)+chr(112)+chr(108)+chr(101)+chr(46)+chr(99)+chr(111)+chr(109)+chr(39)})
import time; time.sleep(0.5)
print(route_open(chr(39)+chr(104)+chr(116)+chr(116)+chr(112)+chr(115)+chr(58)+chr(47)+chr(47)+chr(101)+chr(120)+chr(97)+chr(109)+chr(112)+chr(108)+chr(101)+chr(46)+chr(99)+chr(111)+chr(109)+chr(39)))
import json
print(json.dumps(route_do(chr(39)+chr(116)+chr(121)+chr(112)+chr(101)+chr(32)+chr(35)+chr(115)+chr(101)+chr(97)+chr(114)+chr(99)+chr(104)+chr(124)+chr(72)+chr(101)+chr(108)+chr(108)+chr(111)+chr(39)),indent=2))
print("DONE")
