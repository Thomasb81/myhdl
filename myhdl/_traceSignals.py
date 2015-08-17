#  This file is part of the myhdl library, a Python package for using
#  Python as a Hardware Description Language.
#
#  Copyright (C) 2003-2008 Jan Decaluwe
#
#  The myhdl library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public License as
#  published by the Free Software Foundation; either version 2.1 of the
#  License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful, but
#  WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA

""" myhdl traceSignals module.

"""
from __future__ import absolute_import
from __future__ import print_function



import sys
from inspect import currentframe, getouterframes
import time
import os
path = os.path
import shutil
import ast

import inspect
from myhdl import _simulator, __version__, EnumItemType
from myhdl._extractHierarchy import _HierExtr
from myhdl import TraceSignalsError
from myhdl._ShadowSignal import _TristateSignal, _TristateDriver
from myhdl.conversion._analyze import (_analyzeTopFunc)
from myhdl._compat import StringIO
from myhdl import _util

_tracing = 0
_profileFunc = None

class _error:
    pass
_error.TopLevelName = "result of traceSignals call should be assigned to a top level name"
_error.ArgType = "traceSignals first argument should be a classic function"
_error.MultipleTraces = "Cannot trace multiple instances simultaneously"


class _TraceSignalsClass(object):

    __slot__ = ("name",
                "timescale",
                "tracelists",
                "verilog_tb",
                )

    def __init__(self):
        self.name = None
        self.timescale = "1ns"
        self.tracelists = True
        self.verilog_tb = True

    def __call__(self, dut, *args, **kwargs):
        global _tracing
        if _tracing:
            return dut(*args, **kwargs) # skip
        else:
            # clean start
            sys.setprofile(None)
        from myhdl.conversion import _toVerilog
        if _toVerilog._converting:
            raise TraceSignalsError("Cannot use traceSignals while converting to Verilog")
        if not callable(dut):
            raise TraceSignalsError(_error.ArgType, "got %s" % type(dut))
        if _simulator._tracing:
            raise TraceSignalsError(_error.MultipleTraces)

        _tracing = 1
        try:
            if self.name is None:
                name = dut.__name__
            else:
                name = str(self.name)
            if name is None:
                raise TraceSignalsError(_error.TopLevelName)
            h = _HierExtr(name, dut, *args, **kwargs)
            
#            print (h.hierarchy[0].level)
#            curlevel = 0
#            for inst in h.hierarchy:
#                print(dir(inst))
#                print("level:" + str(inst.level))
#                print("inst:" + inst.name)
#                print("sigdict:" + str(inst.sigdict))
#                for sig_name in inst.sigdict.keys():
#                    print(sig_name + ':' + str(id(inst.sigdict[sig_name])))
#                print("memdict:" + str(inst.memdict))
#                print("delta:" + str(curlevel - inst.level))
#                curlevel = inst.level
#                print("-------------")
       
     
            vcdpath = name + ".vcd"
            if path.exists(vcdpath):
                backup = vcdpath + '.' + str(path.getmtime(vcdpath))
                shutil.copyfile(vcdpath, backup)
                os.remove(vcdpath)
            vcdfile = open(vcdpath, 'w')
            _simulator._tracing = 1
            _simulator._tf = vcdfile
            _writeVcdHeader(vcdfile, self.timescale)
            _writeVcdSigs(vcdfile, h.hierarchy, self.tracelists)

            #bfm
            verilogTBpath = name + "_bfm.v"
            if path.exists(verilogTBpath):
                backup = verilogTBpath + '.' + str(path.getmtime(verilogTBpath))
                shutil.copyfile(verilogTBpath, backup)
                os.remove(verilogTBpath)
            
            verilogTBfile = open(verilogTBpath, 'w')
            _simulator._tbf = verilogTBfile
            
            _toVerilog._writeFileHeader(verilogTBfile,verilogTBpath,self.timescale
                                       +"/10ps" )
            
            top_inst = h.hierarchy[0]
            intf = _analyzeTopFunc(top_inst, dut, *args, **kwargs)
            intf.name = name
            doc = _toVerilog._makeDoc(inspect.getdoc(dut))
            _toVerilog._writeModuleHeader(verilogTBfile, intf, doc)
            
            rec_vis = RecursiveVisitor()
            tree = _util._makeAST(dut)
            rec_vis.visit(tree)

            _writeSigDecls(verilogTBfile,h.hierarchy,rec_vis._db,*args, **kwargs)  
            _registerSignal(h.hierarchy)

        finally:
            _tracing = 0

        return h.top

traceSignals = _TraceSignalsClass()


_codechars = ""
for i in range(33, 127):
    _codechars += chr(i)
_mod = len(_codechars)

def _genNameCode():
    n = 0
    while 1:
        yield _namecode(n)
        n += 1
        
def _namecode(n):
    q, r = divmod(n, _mod)
    code = _codechars[r]
    while q > 0:
        q, r = divmod(q, _mod)
        code = _codechars[r] + code
    return code

def _writeVcdHeader(f, timescale):
    print("$date", file=f)
    print("    %s" % time.asctime(), file=f)
    print("$end", file=f)
    print("$version", file=f)
    print("    MyHDL %s" % __version__, file=f)
    print("$end", file=f)
    print("$timescale", file=f)
    print("    %s" % timescale, file=f)
    print("$end", file=f)
    print(file=f)

def _getSval(s):
    if isinstance(s, _TristateSignal):
        sval = s._orival
    elif isinstance(s, _TristateDriver):
        sval = s._sig._orival
    else:
        sval = s._val
    return sval

def _writeVcdSigs(f, hierarchy, tracelists):
    curlevel = 0
    namegen = _genNameCode()
    siglist = []
    for inst in hierarchy:
        level = inst.level
        name = inst.name
        sigdict = inst.sigdict
        memdict = inst.memdict
        delta = curlevel - level
        curlevel = level
        assert(delta >= -1)
        if delta >= 0:
            for i in range(delta + 1):
                print("$upscope $end", file=f)
        print("$scope module %s $end" % name, file=f)
        for n, s in sigdict.items():
            sval = _getSval(s)
            if sval is None:
                raise ValueError("%s of module %s has no initial value" % (n, name))
            if not s._tracing:
                s._tracing = 1
                s._code = next(namegen)
                #s._name = n
                siglist.append(s)
            w = s._nrbits
            # use real for enum strings
            if w and not isinstance(sval, EnumItemType):
                if w == 1:
                    print("$var reg 1 %s %s $end" % (s._code, n), file=f)
                else:
                    print("$var reg %s %s %s $end" % (w, s._code, n), file=f)
            else:
                print("$var real 1 %s %s $end" % (s._code, n), file=f)
        # Memory dump by Frederik Teichert, http://teichert-ing.de, date: 2011.03.28
        # The Value Change Dump standard doesn't support multidimensional arrays so 
        # all memories are flattened and renamed.
        if tracelists:
            for n in memdict.keys():
                print("$scope module {} $end" .format(n), file=f)
                memindex = 0
                for s in memdict[n].mem:
                    sval = _getSval(s)
                    if sval is None:
                        raise ValueError("%s of module %s has no initial value" % (n, name))
                    if not s._tracing:
                        s._tracing = 1
                        s._code = next(namegen)
                        siglist.append(s)
                    w = s._nrbits
                    if w:
                        if w == 1:
                            print("$var reg 1 %s %s(%i) $end" % (s._code, n, memindex), file=f)
                        else:
                            print("$var reg %s %s %s(%i) $end" % (w, s._code, n, memindex), file=f)
                    else:
                        print("$var real 1 %s %s(%i) $end" % (s._code, n, memindex), file=f)
                    memindex += 1
                print("$upscope $end", file=f)
    for i in range(curlevel):
        print("$upscope $end", file=f)
    print(file=f)
    print("$enddefinitions $end", file=f)
    print("$dumpvars", file=f)
    for s in siglist:
        s._printVcd() # initial value
    print("$end", file=f)
            
def _writeSigDecls(filename,hierarchy,db,*args, **kwargs):

    wire_dict =  []
    #declare testbench wire
    for name, sigobj in hierarchy[0].sigdict.items():
        wire_dict.append(name)
        w = sigobj._nrbits
        if w == 1:
            print("wire %s;" % (name), file=filename)
        else:
            print("wire [%i:0] %s;" %(w-1,name), file=filename)
    
    #declare instance
    
    for elem in hierarchy:
        if elem.level == 2:
            pm = StringIO()
            for inst, module, intf in db:
                if inst == elem.name:
                    for port in intf:
                        if port in wire_dict:
                            print("  .%s(%s),"%(port,port),file=pm)

            print(pm.getvalue()[:-2], file=filename)
            print(");", file=filename)

    print("initial begin", file=filename)

    

def _registerSignal(hierarchy):
    for name, sigobj in hierarchy[0].sigdict.items():
        sigobj._name = name
        sigobj._printTB = True


class RecursiveVisitor(ast.NodeVisitor):
    """ example recursive visitor """
    __slots__ = ['_db']

    def __init__(self):
        self._db = []

    def recursive(func):
        """ decorator to make visitor work recursive """
        def wrapper(self,node):
            func(self,node)
            for child in ast.iter_child_nodes(node):
                self.visit(child)
        return wrapper

    @recursive
    def visit_Assign(self,node):
        """ visit a Assign node and visits it recursively"""
        if isinstance(node.value,ast.Call):
            if isinstance(node.value.func,ast.Name):
                if node.value.func.id not in ['Signal','bool','always','delay','True','False']:
                    if isinstance(node.value.args[0],ast.Name):
                        print (node.targets[0].id)
                        self._db.append([
                                   node.targets[0].id,
                                   node.value.func.id,
                                   [arg.id for arg in node.value.args]
                                    ])
    
    @recursive
    def visit_Name(self,node):
        """ visit a Name node and visits it recursively"""
        pass
        

    @recursive
    def visit_Call(self,node):
        """ visit a Call node and visits it recursively"""
#        if isinstance(node.func,ast.Name):
#            if node.func.id not in ['Signal','bool','always','delay']:
#                self._db.append(node.func.id,[arg.id for arg in node.args]])

    @recursive
    def visit_FunctionDef(self,node):
        """ visit a Function node and visits it recursively"""
        pass

    @recursive
    def visit_Module(self,node):
        """ visit a Module node and the visits recursively"""
        pass

    def generic_visit(self,node):
        pass


