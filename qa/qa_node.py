#
#

# Copyright (C) 2007 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.


from ganeti import utils
from ganeti import constants
from ganeti import query
from ganeti import serializer

import qa_config
import qa_error
import qa_utils

from qa_utils import AssertCommand


def _NodeAdd(node, readd=False):
  if not readd and node.get('_added', False):
    raise qa_error.Error("Node %s already in cluster" % node['primary'])
  elif readd and not node.get('_added', False):
    raise qa_error.Error("Node %s not yet in cluster" % node['primary'])

  cmd = ['gnt-node', 'add', "--no-ssh-key-check"]
  if node.get('secondary', None):
    cmd.append('--secondary-ip=%s' % node['secondary'])
  if readd:
    cmd.append('--readd')
  cmd.append(node['primary'])

  AssertCommand(cmd)

  node['_added'] = True


def _NodeRemove(node):
  AssertCommand(["gnt-node", "remove", node["primary"]])
  node['_added'] = False


def TestNodeAddAll():
  """Adding all nodes to cluster."""
  master = qa_config.GetMasterNode()
  for node in qa_config.get('nodes'):
    if node != master:
      _NodeAdd(node, readd=False)


def MarkNodeAddedAll():
  """Mark all nodes as added.

  This is useful if we don't create the cluster ourselves (in qa).

  """
  master = qa_config.GetMasterNode()
  for node in qa_config.get('nodes'):
    if node != master:
      node['_added'] = True


def TestNodeRemoveAll():
  """Removing all nodes from cluster."""
  master = qa_config.GetMasterNode()
  for node in qa_config.get('nodes'):
    if node != master:
      _NodeRemove(node)


def TestNodeReadd(node):
  """gnt-node add --readd"""
  _NodeAdd(node, readd=True)


def TestNodeInfo():
  """gnt-node info"""
  AssertCommand(["gnt-node", "info"])


def TestNodeVolumes():
  """gnt-node volumes"""
  AssertCommand(["gnt-node", "volumes"])


def TestNodeStorage():
  """gnt-node storage"""
  master = qa_config.GetMasterNode()

  for storage_type in constants.VALID_STORAGE_TYPES:
    # Test simple list
    AssertCommand(["gnt-node", "list-storage", "--storage-type", storage_type])

    # Test all storage fields
    cmd = ["gnt-node", "list-storage", "--storage-type", storage_type,
           "--output=%s" % ",".join(list(constants.VALID_STORAGE_FIELDS) +
                                    [constants.SF_NODE, constants.SF_TYPE])]
    AssertCommand(cmd)

    # Get list of valid storage devices
    cmd = ["gnt-node", "list-storage", "--storage-type", storage_type,
           "--output=node,name,allocatable", "--separator=|",
           "--no-headers"]
    output = qa_utils.GetCommandOutput(master["primary"],
                                       utils.ShellQuoteArgs(cmd))

    # Test with up to two devices
    testdevcount = 2

    for line in output.splitlines()[:testdevcount]:
      (node_name, st_name, st_allocatable) = line.split("|")

      # Dummy modification without any changes
      cmd = ["gnt-node", "modify-storage", node_name, storage_type, st_name]
      AssertCommand(cmd)

      # Make sure we end up with the same value as before
      if st_allocatable.lower() == "y":
        test_allocatable = ["no", "yes"]
      else:
        test_allocatable = ["yes", "no"]

      fail = (constants.SF_ALLOCATABLE not in
              constants.MODIFIABLE_STORAGE_FIELDS.get(storage_type, []))

      for i in test_allocatable:
        AssertCommand(["gnt-node", "modify-storage", "--allocatable", i,
                       node_name, storage_type, st_name], fail=fail)

      # Test repair functionality
      fail = (constants.SO_FIX_CONSISTENCY not in
              constants.VALID_STORAGE_OPERATIONS.get(storage_type, []))
      AssertCommand(["gnt-node", "repair-storage", node_name,
                     storage_type, st_name], fail=fail)


def TestNodeFailover(node, node2):
  """gnt-node failover"""
  if qa_utils.GetNodeInstances(node2, secondaries=False):
    raise qa_error.UnusableNodeError("Secondary node has at least one"
                                     " primary instance. This test requires"
                                     " it to have no primary instances.")

  # Fail over to secondary node
  AssertCommand(["gnt-node", "failover", "-f", node["primary"]])

  # ... and back again.
  AssertCommand(["gnt-node", "failover", "-f", node2["primary"]])


def TestNodeEvacuate(node, node2):
  """gnt-node evacuate"""
  node3 = qa_config.AcquireNode(exclude=[node, node2])
  try:
    if qa_utils.GetNodeInstances(node3, secondaries=True):
      raise qa_error.UnusableNodeError("Evacuation node has at least one"
                                       " secondary instance. This test requires"
                                       " it to have no secondary instances.")

    # Evacuate all secondary instances
    AssertCommand(["gnt-node", "evacuate", "-f",
                   "--new-secondary=%s" % node3["primary"], node2["primary"]])

    # ... and back again.
    AssertCommand(["gnt-node", "evacuate", "-f",
                   "--new-secondary=%s" % node2["primary"], node3["primary"]])
  finally:
    qa_config.ReleaseNode(node3)


def TestNodeModify(node):
  """gnt-node modify"""
  for flag in ["master-candidate", "drained", "offline"]:
    for value in ["yes", "no"]:
      AssertCommand(["gnt-node", "modify", "--force",
                     "--%s=%s" % (flag, value), node["primary"]])

  AssertCommand(["gnt-node", "modify", "--master-candidate=yes",
                 "--auto-promote", node["primary"]])


def _CreateOobScriptStructure():
  """Create a simple OOB handling script and its structure."""
  master = qa_config.GetMasterNode()

  data_path = qa_utils.UploadData(master["primary"], "")
  verify_path = qa_utils.UploadData(master["primary"], "")
  exit_code_path = qa_utils.UploadData(master["primary"], "")

  oob_script = (("#!/bin/bash\n"
                 "echo \"$@\" > %s\n"
                 "cat %s\n"
                 "exit $(< %s)\n") %
                (utils.ShellQuote(verify_path), utils.ShellQuote(data_path),
                 utils.ShellQuote(exit_code_path)))
  oob_path = qa_utils.UploadData(master["primary"], oob_script, mode=0700)

  return [oob_path, verify_path, data_path, exit_code_path]


def _UpdateOobFile(path, data):
  """Updates the data file with data."""
  master = qa_config.GetMasterNode()
  qa_utils.UploadData(master["primary"], data, filename=path)


def _AssertOobCall(verify_path, expected_args):
  """Assert the OOB call was performed with expetected args."""
  master = qa_config.GetMasterNode()

  verify_output_cmd = utils.ShellQuoteArgs(["cat", verify_path])
  output = qa_utils.GetCommandOutput(master["primary"], verify_output_cmd)

  qa_utils.AssertEqual(expected_args, output.strip())


def TestOutOfBand():
  """gnt-node power"""
  master = qa_config.GetMasterNode()

  (oob_path, verify_path,
   data_path, exit_code_path) = _CreateOobScriptStructure()

  try:
    AssertCommand(["gnt-cluster", "modify", "--node-parameters",
                   "oob_program=%s" % oob_path])

    # No data, exit 0
    _UpdateOobFile(exit_code_path, "0")

    AssertCommand(["gnt-node", "power", "on", master["primary"]])
    _AssertOobCall(verify_path, "power-on %s" % master["primary"])

    AssertCommand(["gnt-node", "power", "off", master["primary"]])
    _AssertOobCall(verify_path, "power-off %s" % master["primary"])

    AssertCommand(["gnt-node", "power", "cycle", master["primary"]])
    _AssertOobCall(verify_path, "power-cycle %s" % master["primary"])

    # This command should fail as it expects output which isn't provided yet
    # But it should have called the oob helper nevermind
    AssertCommand(["gnt-node", "power", "status", master["primary"]],
                  fail=True)
    _AssertOobCall(verify_path, "power-status %s" % master["primary"])

    # Data, exit 0
    _UpdateOobFile(data_path, serializer.DumpJson({ "powered": True }))

    AssertCommand(["gnt-node", "power", "status", master["primary"]])
    _AssertOobCall(verify_path, "power-status %s" % master["primary"])

    AssertCommand(["gnt-node", "power", "on", master["primary"]], fail=True)
    _AssertOobCall(verify_path, "power-on %s" % master["primary"])

    AssertCommand(["gnt-node", "power", "off", master["primary"]], fail=True)
    _AssertOobCall(verify_path, "power-off %s" % master["primary"])

    AssertCommand(["gnt-node", "power", "cycle", master["primary"]], fail=True)
    _AssertOobCall(verify_path, "power-cycle %s" % master["primary"])

    # Data, exit 1 (all should fail)
    _UpdateOobFile(exit_code_path, "1")

    AssertCommand(["gnt-node", "power", "on", master["primary"]], fail=True)
    _AssertOobCall(verify_path, "power-on %s" % master["primary"])

    AssertCommand(["gnt-node", "power", "off", master["primary"]], fail=True)
    _AssertOobCall(verify_path, "power-off %s" % master["primary"])

    AssertCommand(["gnt-node", "power", "cycle", master["primary"]], fail=True)
    _AssertOobCall(verify_path, "power-cycle %s" % master["primary"])

    AssertCommand(["gnt-node", "power", "status", master["primary"]],
                  fail=True)
    _AssertOobCall(verify_path, "power-status %s" % master["primary"])

    # No data, exit 1 (all should fail)
    _UpdateOobFile(data_path, "")
    AssertCommand(["gnt-node", "power", "on", master["primary"]], fail=True)
    _AssertOobCall(verify_path, "power-on %s" % master["primary"])

    AssertCommand(["gnt-node", "power", "off", master["primary"]], fail=True)
    _AssertOobCall(verify_path, "power-off %s" % master["primary"])

    AssertCommand(["gnt-node", "power", "cycle", master["primary"]], fail=True)
    _AssertOobCall(verify_path, "power-cycle %s" % master["primary"])

    AssertCommand(["gnt-node", "power", "status", master["primary"]],
                  fail=True)
    _AssertOobCall(verify_path, "power-status %s" % master["primary"])

    # Different OOB script for node
    verify_path2 = qa_utils.UploadData(master["primary"], "")
    oob_script = ("#!/bin/sh\n"
                  "echo \"$@\" > %s\n") % verify_path2
    oob_path2 = qa_utils.UploadData(master["primary"], oob_script, mode=0700)

    try:
      AssertCommand(["gnt-node", "modify", "--node-parameters",
                     "oob_program=%s" % oob_path2, master["primary"]])
      AssertCommand(["gnt-node", "power", "on", master["primary"]])
      _AssertOobCall(verify_path2, "power-on %s" % master["primary"])
    finally:
      AssertCommand(["gnt-node", "modify", "--node-parameters",
                     "oob_program=default", master["primary"]])
      AssertCommand(["rm", "-f", oob_path2, verify_path2])
  finally:
    AssertCommand(["gnt-cluster", "modify", "--node-parameters",
                   "oob_program=default"])
    AssertCommand(["rm", "-f", oob_path, verify_path, data_path,
                   exit_code_path])


def TestNodeList():
  """gnt-node list"""
  qa_utils.GenericQueryTest("gnt-node", query.NODE_FIELDS.keys())


def TestNodeListFields():
  """gnt-node list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-node", query.NODE_FIELDS.keys())
